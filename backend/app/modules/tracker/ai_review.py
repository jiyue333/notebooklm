from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import structlog

from app.core.config import get_settings
from app.infra.telemetry.metrics import (
    observe_ai_online_review_bad_case,
    observe_ai_online_review_result,
    observe_ai_online_review_score,
)
from app.modules.tracker.review_utils import append_jsonl, extract_json_object, is_sampled

logger = structlog.get_logger(__name__)

AI_REVIEW_PROMPT = """你是 NotebookLM 的在线质量评审器。

请根据给定的任务、问题、回答和证据，对回答做三个 0 到 1 的评分：
- groundedness: 回答是否被给定证据支持
- faithfulness: 回答是否避免了无依据或扭曲表述
- completeness: 回答是否覆盖了用户问题的关键点

返回严格 JSON：
{
  "groundedness": 0.0,
  "faithfulness": 0.0,
  "completeness": 0.0,
  "overall": 0.0,
  "bad_case": false,
  "reasons": ["reason1", "reason2"]
}
"""


@dataclass(slots=True)
class AiReviewScores:
    groundedness: float
    faithfulness: float
    completeness: float
    overall: float
    bad_case: bool
    reasons: list[str]


class AiReviewTracker:
    def __init__(self, *, operation: str, route: str | None = None) -> None:
        self.operation = operation
        self.route = route or "none"
        self._settings = get_settings()

    def schedule(
        self,
        *,
        sample_key: str,
        model,
        metadata: dict,
        review_payload: dict,
    ) -> bool:
        if not self._settings.ai_review_sampling_enabled or self._settings.ai_review_sampling_rate <= 0:
            return False

        selected = is_sampled(key=sample_key, sample_rate=self._settings.ai_review_sampling_rate)
        observe_ai_online_review_result(
            operation=self.operation,
            route=self.route,
            reviewer="llm",
            result="selected" if selected else "skipped",
        )
        if not selected:
            return False

        asyncio.create_task(
            self._run_review(
                model=model,
                metadata=metadata,
                review_payload=review_payload,
            )
        )
        return True

    async def _run_review(self, *, model, metadata: dict, review_payload: dict) -> None:
        try:
            result = await model.ainvoke(
                _build_prompt(review_payload),
                config={"run_name": "ai_online_review", "metadata": metadata},
            )
            parsed = extract_json_object(_extract_model_text(result))
            if parsed is None:
                raise ValueError("review output is not valid JSON")
            scores = _normalize_scores(parsed)
        except Exception as exc:  # pragma: no cover - operational path
            observe_ai_online_review_result(
                operation=self.operation,
                route=self.route,
                reviewer="llm",
                result="error",
            )
            logger.warning(
                "ai.online_review_failed",
                operation=self.operation,
                route=self.route,
                error=str(exc),
            )
            return

        payload = {
            "captured_at": datetime.now(UTC).isoformat(),
            "operation": self.operation,
            "route": self.route,
            "metadata": metadata,
            "review": asdict(scores),
            "payload": review_payload,
        }
        try:
            await asyncio.to_thread(append_jsonl, _resolve_output_path(), payload)
            if scores.bad_case or scores.overall <= self._settings.ai_review_bad_case_threshold:
                await asyncio.to_thread(append_jsonl, _resolve_bad_case_path(), payload)
        except Exception as exc:  # pragma: no cover - operational path
            observe_ai_online_review_result(
                operation=self.operation,
                route=self.route,
                reviewer="llm",
                result="error",
            )
            logger.warning(
                "ai.online_review_write_failed",
                operation=self.operation,
                route=self.route,
                error=str(exc),
            )
            return

        for score_type, score_value in (
            ("groundedness", scores.groundedness),
            ("faithfulness", scores.faithfulness),
            ("completeness", scores.completeness),
            ("overall", scores.overall),
        ):
            observe_ai_online_review_score(
                operation=self.operation,
                route=self.route,
                reviewer="llm",
                score_type=score_type,
                score=score_value,
            )
        if scores.bad_case or scores.overall <= self._settings.ai_review_bad_case_threshold:
            observe_ai_online_review_bad_case(
                operation=self.operation,
                route=self.route,
                reviewer="llm",
                reason="judge_flagged",
            )
        observe_ai_online_review_result(
            operation=self.operation,
            route=self.route,
            reviewer="llm",
            result="written",
        )


def _build_prompt(review_payload: dict) -> str:
    return "\n\n".join([AI_REVIEW_PROMPT, "评审输入：", str(review_payload)])


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


def _normalize_scores(payload: dict) -> AiReviewScores:
    groundedness = _clamp_score(payload.get("groundedness", 0.0))
    faithfulness = _clamp_score(payload.get("faithfulness", 0.0))
    completeness = _clamp_score(payload.get("completeness", 0.0))
    overall = _clamp_score(payload.get("overall", (groundedness + faithfulness + completeness) / 3))
    reasons = payload.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    return AiReviewScores(
        groundedness=groundedness,
        faithfulness=faithfulness,
        completeness=completeness,
        overall=overall,
        bad_case=bool(payload.get("bad_case", False)),
        reasons=[str(reason).strip() for reason in reasons if str(reason).strip()],
    )


def _clamp_score(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = 0.0
    return round(max(0.0, min(numeric, 1.0)), 4)


def _resolve_output_path() -> Path:
    root = get_settings().ai_review_output_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / f"ai-review-{datetime.now(UTC):%Y%m%d}.jsonl"


def _resolve_bad_case_path() -> Path:
    root = get_settings().ai_review_bad_case_output_dir
    root.mkdir(parents=True, exist_ok=True)
    return root / f"ai-review-badcases-{datetime.now(UTC):%Y%m%d}.jsonl"
