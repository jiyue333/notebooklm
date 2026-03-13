"""Search 采样评审 Tracker。

负责对线上搜索请求做规则评审和可选的 LLM 评审，并将坏例子回流到 JSONL。
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
import json
from pathlib import Path

import structlog

from app.core.config import get_settings
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import (
    observe_search_review_bad_case,
    observe_search_review_sample,
    observe_search_review_score,
)
from app.modules.search.sessions.dto import SearchCandidateDTO
from app.modules.search.sessions.quality import SearchQualitySnapshot
from app.modules.tracker.review_utils import append_jsonl, extract_json_object, is_sampled

logger = structlog.get_logger(__name__)

SEARCH_REVIEW_PROMPT = """你是 NotebookLM 的搜索结果质量评审器。

请根据查询、freshness 约束和候选结果，给出 0 到 1 的评分：
- relevance
- freshness
- authority
- coverage
- overall

如果结果明显不满足查询或 freshness / authority 需求，请把 bad_case 设为 true。

返回严格 JSON：
{
  "relevance": 0.0,
  "freshness": 0.0,
  "authority": 0.0,
  "coverage": 0.0,
  "overall": 0.0,
  "bad_case": false,
  "reasons": ["reason1", "reason2"]
}
"""


class SearchReviewTracker:
    def __init__(self, *, mode: str, execution: str, provider: str) -> None:
        self.mode = mode
        self.execution = execution
        self.provider = provider
        self._settings = get_settings()

    async def capture(
        self,
        *,
        user=None,
        search_session_id: str,
        notebook_id: str,
        query: str,
        freshness_hours: int | None,
        candidates: list[SearchCandidateDTO],
        quality_snapshot: SearchQualitySnapshot,
    ) -> bool:
        settings = self._settings
        review_mode = settings.search_review_sampling_mode
        if not settings.search_review_sampling_enabled or settings.search_review_sampling_rate <= 0:
            return False

        selected = is_sampled(
            key=search_session_id,
            sample_rate=settings.search_review_sampling_rate,
        )
        observe_search_review_sample(
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
            review_mode=review_mode,
            result="selected" if selected else "skipped",
        )
        if not selected:
            return False

        payload = self._build_base_payload(
            search_session_id=search_session_id,
            notebook_id=notebook_id,
            query=query,
            freshness_hours=freshness_hours,
            candidates=candidates,
            quality_snapshot=quality_snapshot,
            review_mode=review_mode,
        )

        try:
            await asyncio.to_thread(append_jsonl, _resolve_output_path(), payload)
            if _is_rule_bad_case(quality_snapshot, threshold=settings.search_review_bad_case_threshold):
                await asyncio.to_thread(append_jsonl, _resolve_bad_case_path(), {**payload, "reviewer": "rule"})
                observe_search_review_bad_case(
                    mode=self.mode,
                    execution=self.execution,
                    provider=self.provider,
                    reviewer="rule",
                    reason="rule_threshold",
                )
        except Exception as exc:  # pragma: no cover - operational path
            observe_search_review_sample(
                mode=self.mode,
                execution=self.execution,
                provider=self.provider,
                review_mode=review_mode,
                result="error",
            )
            logger.warning(
                "search.review_sample_write_failed",
                search_session_id=search_session_id,
                error=str(exc),
            )
            return False

        observe_search_review_sample(
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
            review_mode=review_mode,
            result="written",
        )

        if review_mode in {"llm", "rule_llm"} and user is not None:
            model = build_user_chat_model(user)
            if model is not None:
                asyncio.create_task(
                    self._run_llm_review(
                        model=model,
                        base_payload=payload,
                    )
                )
            else:
                observe_search_review_sample(
                    mode=self.mode,
                    execution=self.execution,
                    provider=self.provider,
                    review_mode="llm",
                    result="llm_skipped_unconfigured",
                )
        return True

    def _build_base_payload(
        self,
        *,
        search_session_id: str,
        notebook_id: str,
        query: str,
        freshness_hours: int | None,
        candidates: list[SearchCandidateDTO],
        quality_snapshot: SearchQualitySnapshot,
        review_mode: str,
    ) -> dict:
        return {
            "captured_at": datetime.now(UTC).isoformat(),
            "search_session_id": search_session_id,
            "notebook_id": notebook_id,
            "query": query,
            "mode": self.mode,
            "execution": self.execution,
            "provider": self.provider,
            "review_mode": review_mode,
            "review_status": "completed",
            "freshness_hours": freshness_hours,
            "result_count": len(candidates),
            "rule_review": asdict(quality_snapshot),
            "results": [
                {
                    "rank": candidate.display_rank,
                    "title": candidate.title,
                    "url": candidate.raw_url,
                    "domain": candidate.domain,
                    "author": candidate.author,
                    "published_at": candidate.published_at.isoformat() if candidate.published_at else None,
                }
                for candidate in candidates[:10]
            ],
        }

    async def _run_llm_review(self, *, model, base_payload: dict) -> None:
        try:
            result = await model.ainvoke(
                _build_llm_review_prompt(base_payload),
                config={
                    "run_name": "search_review_judge",
                    "metadata": {
                        "search_session_id": base_payload["search_session_id"],
                        "notebook_id": base_payload["notebook_id"],
                        "provider": self.provider,
                    },
                },
            )
            parsed = extract_json_object(_extract_model_text(result))
            if parsed is None:
                raise ValueError("search review output is not valid JSON")
        except Exception as exc:  # pragma: no cover - operational path
            observe_search_review_sample(
                mode=self.mode,
                execution=self.execution,
                provider=self.provider,
                review_mode="llm",
                result="llm_error",
            )
            logger.warning(
                "search.review_llm_failed",
                search_session_id=base_payload["search_session_id"],
                error=str(exc),
            )
            return

        llm_review = _normalize_llm_review(parsed)
        payload = {
            **base_payload,
            "llm_review": llm_review,
        }
        try:
            await asyncio.to_thread(append_jsonl, _resolve_llm_output_path(), payload)
            if llm_review["bad_case"] or llm_review["overall"] <= self._settings.search_review_bad_case_threshold:
                await asyncio.to_thread(append_jsonl, _resolve_bad_case_path(), {**payload, "reviewer": "llm"})
                observe_search_review_bad_case(
                    mode=self.mode,
                    execution=self.execution,
                    provider=self.provider,
                    reviewer="llm",
                    reason="judge_flagged",
                )
        except Exception as exc:  # pragma: no cover - operational path
            observe_search_review_sample(
                mode=self.mode,
                execution=self.execution,
                provider=self.provider,
                review_mode="llm",
                result="llm_write_error",
            )
            logger.warning(
                "search.review_llm_write_failed",
                search_session_id=base_payload["search_session_id"],
                error=str(exc),
            )
            return

        for score_type in ("relevance", "freshness", "authority", "coverage", "overall"):
            observe_search_review_score(
                mode=self.mode,
                execution=self.execution,
                provider=self.provider,
                reviewer="llm",
                score_type=score_type,
                score=float(llm_review[score_type]),
            )
        observe_search_review_sample(
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
            review_mode="llm",
            result="llm_written",
        )


def _is_rule_bad_case(snapshot: SearchQualitySnapshot, *, threshold: float) -> bool:
    return snapshot.overall <= threshold or not snapshot.freshness_satisfied or not snapshot.authority_hit


def _resolve_output_path() -> Path:
    root = get_settings().search_review_output_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / f"search-review-{datetime.now(UTC):%Y%m%d}.jsonl"


def _resolve_llm_output_path() -> Path:
    root = get_settings().search_review_output_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / f"search-review-llm-{datetime.now(UTC):%Y%m%d}.jsonl"


def _resolve_bad_case_path() -> Path:
    root = get_settings().search_review_bad_case_output_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / f"search-review-badcases-{datetime.now(UTC):%Y%m%d}.jsonl"


def _build_llm_review_prompt(payload: dict) -> str:
    return "\n\n".join(
        [
            SEARCH_REVIEW_PROMPT,
            "评审输入：",
            json.dumps(payload, ensure_ascii=False),
        ]
    )


def _extract_model_text(result) -> str:
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif hasattr(item, "text"):
                parts.append(str(item.text))
        return "".join(parts)
    return str(result)


def _normalize_llm_review(payload: dict) -> dict:
    return {
        "relevance": _clamp_score(payload.get("relevance", 0.0)),
        "freshness": _clamp_score(payload.get("freshness", 0.0)),
        "authority": _clamp_score(payload.get("authority", 0.0)),
        "coverage": _clamp_score(payload.get("coverage", 0.0)),
        "overall": _clamp_score(payload.get("overall", 0.0)),
        "bad_case": bool(payload.get("bad_case", False)),
        "reasons": [str(reason).strip() for reason in (payload.get("reasons") or []) if str(reason).strip()],
    }


def _clamp_score(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return round(max(0.0, min(numeric, 1.0)), 4)
