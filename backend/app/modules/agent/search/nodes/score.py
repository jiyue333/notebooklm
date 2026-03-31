"""评分节点：规则打分、LLM 辅助评分与候选筛选。"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_search_stage
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search.state import SearchCandidate, SearchGraphState, SearchTaskSpec
from app.modules.agent.search.utils import _blend_scores, _clamp, _elapsed_ms, _safe_text, _token_similarity

logger = structlog.get_logger(__name__)

_AUTHORITY_PATTERNS = [
    (".gov", 0.95),
    (".edu", 0.92),
    (".ac.", 0.9),
    ("arxiv.org", 0.9),
    ("docs.", 0.84),
    ("developer.", 0.82),
    ("github.com", 0.78),
    ("nature.com", 0.9),
    ("science.org", 0.9),
    ("who.int", 0.94),
    ("medium.com", 0.58),
]
_SCORE_CANDIDATE_CAP_BY_MODE = {"fast": 20, "auto": 24, "deep": 30}
_SELECTION_THRESHOLD_BY_MODE = {"fast": 0.58, "auto": 0.6, "deep": 0.62}

_SCORE_SYSTEM_PROMPT = """\
你是一位严谨的搜索结果评估专家。请根据用户的问题评估每一条候选搜索结果。

## 评分流程
对每个候选，先写出 strength（最突出的优点）和 weakness（最明显的不足），然后再给出各维度分数。

## 评分维度与标准 (0-1)

### relevance_score — 与问题的相关性
- ≥0.9: 精确匹配问题核心意图，直接回答问题
- 0.7-0.89: 高度相关，提供有价值的信息
- 0.5-0.69: 部分相关，涉及相关话题但不直接回答
- 0.3-0.49: 勉强沾边，角度偏离
- <0.3: 几乎不相关

### authority_score — 来源权威性
- ≥0.9: 顶级权威（政府/学术机构/领域官方文档）
- 0.7-0.89: 可靠专业来源（知名媒体/行业领袖/官方博客）
- 0.5-0.69: 一般来源（社区内容/个人博客）
- <0.5: 来源可信度存疑

### freshness_score — 时效性
- ≥0.9: 近期发布，信息非常新
- 0.7-0.89: 相对较新，信息仍然有效
- 0.5-0.69: 有一定时间，部分内容可能已过时
- <0.5: 信息较旧

### content_quality_score — 内容质量
- ≥0.9: 内容翔实深入、结构清晰、论据充分
- 0.7-0.89: 有一定深度，信息较完整
- 0.5-0.69: 内容一般，信息较浅或不够完整
- <0.5: 内容薄弱或信息量极少

## 重要规则
- 使用完整的分数范围：优秀结果给 ≥0.85，差的结果给 ≤0.35，避免所有候选都给 0.5-0.7
- relevance_score 是最关键的维度，请严格评估与问题的匹配度
- 不要遗漏任何候选的 index"""


class _ScoreItem(BaseModel):
    index: int
    strength: str = Field(default="", description="该候选最突出的优点（1句话）")
    weakness: str = Field(default="", description="该候选最明显的不足（1句话）")
    relevance_score: float = Field(ge=0, le=1, description="与问题的相关性 0-1")
    authority_score: float = Field(ge=0, le=1, description="来源权威性 0-1")
    freshness_score: float = Field(ge=0, le=1, description="时效性 0-1")
    content_quality_score: float = Field(ge=0, le=1, description="内容质量 0-1")
    rationale: str = Field(default="", description="综合评分理由")


class _ScoreBatchOutput(BaseModel):
    items: list[_ScoreItem] = Field(default_factory=list)


def make_score_node(model):
    """返回绑定了 *model* 的评分 LangGraph 节点函数。"""

    async def score_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        with start_span("search.score", attributes={"search.mode": mode, "search.candidate_count": len(state.get("recall_candidates", []))}):
            scored, score_mode, llm_score_unavailable = await _score_candidates(model, state, mode=mode)
            target_count = state["target_count"]
            selected = _select_candidates(
                scored,
                target_count=target_count,
                mode=mode,
                task_spec=state["task_spec"],
            )
            score_ms = _elapsed_ms(t0)
            logger.info(
                "search.score_done",
                mode=mode,
                duration_ms=score_ms,
                candidate_count=len(scored),
                selected_count=len(selected),
                score_mode=score_mode,
                top_score=round(scored[0].final_score, 4) if scored else 0,
            )
            observe_search_stage(stage="score", mode=mode, status="ok", duration_ms=score_ms)
            return {
                "recall_candidates": scored,
                "selected_candidates": selected,
                "debug": {
                    **state.get("debug", {}),
                    "scoreMode": score_mode,
                    "scoreThreshold": _SELECTION_THRESHOLD_BY_MODE.get(mode, 0.6),
                    "scoredCandidateCount": len(scored),
                    "llmScoreUnavailable": llm_score_unavailable,
                },
            }

    return score_node


# ---------------------------------------------------------------------------
# 规则评分函数
# ---------------------------------------------------------------------------

def _authority_score(domain: str) -> float:
    lowered = domain.lower()
    for pattern, score in _AUTHORITY_PATTERNS:
        if pattern in lowered:
            return score
    if lowered.endswith(".org"):
        return 0.7
    return 0.56


def _freshness_score(published_at: datetime | None, time_sensitivity: str) -> float:
    if not published_at:
        return 0.45 if time_sensitivity == "high" else 0.55
    now = datetime.now(UTC)
    delta_hours = max((now - published_at.astimezone(UTC)).total_seconds() / 3600, 0)
    if time_sensitivity == "high":
        if delta_hours <= 48:
            return 1.0
        if delta_hours <= 24 * 14:
            return 0.82
        if delta_hours <= 24 * 60:
            return 0.62
        return 0.38
    if delta_hours <= 24 * 30:
        return 0.82
    if delta_hours <= 24 * 180:
        return 0.68
    return 0.5


def _content_quality_score(candidate: SearchCandidate) -> float:
    text = " ".join(candidate.highlights) or candidate.description
    length_score = min(len(text) / 360, 1.0)
    author_bonus = 0.08 if candidate.author else 0.0
    highlight_bonus = min(len(candidate.highlights) * 0.08, 0.16)
    return round(_clamp(0.46 + length_score * 0.3 + author_bonus + highlight_bonus), 4)


def _novelty_score(
    *,
    candidate: SearchCandidate,
    notebook_summaries: list[dict[str, str]],
) -> float:
    candidate_text = f"{candidate.title} {' '.join(candidate.highlights[:2])}".lower()
    overlaps = []
    for item in notebook_summaries[:8]:
        summary_text = f"{_safe_text(item.get('title'))} {_safe_text(item.get('summaryText'))[:120]}".lower()
        overlaps.append(_token_similarity(candidate_text, summary_text))
    max_overlap = max(overlaps or [0.0])
    return round(_clamp(1.0 - max_overlap), 4)


def _coverage_score(*, candidate: SearchCandidate, preferred_match: bool) -> float:
    text = " ".join(candidate.highlights).strip() or candidate.description
    highlight_depth = min(len(text) / 260.0, 1.0)
    source_signal = 0.1 if candidate.provider in {"exa", "tavily"} else 0.0
    preferred_bonus = 0.2 if preferred_match else 0.0
    return round(_clamp(0.4 + highlight_depth * 0.3 + source_signal + preferred_bonus), 4)


def _weighted_score(score_breakdown: dict[str, float], weights: dict[str, float]) -> float:
    total = 0.0
    for key, weight in weights.items():
        total += score_breakdown.get(key, 0.0) * weight
    return round(total, 4)


def _build_reasoning(
    *,
    candidate: SearchCandidate,
    score_breakdown: dict[str, float],
    rationale: str,
    strength: str = "",
    preferred_site: str | None,
) -> tuple[str, list[str]]:
    parts: list[str] = []
    tags: list[str] = []
    if preferred_site:
        parts.append(f"命中偏好站点 {preferred_site}")
        tags.append("preferred_site")
    dimension_labels = {
        "authority_score": ("来源权威", "authority"),
        "relevance_score": ("与问题相关", "relevance"),
        "novelty_score": ("补充新视角", "novelty"),
        "freshness_score": ("信息较新", "freshness"),
        "content_quality_score": ("内容信息量高", "content_quality"),
        "coverage_score": ("覆盖维度完整", "coverage"),
    }
    top_dimensions = sorted(score_breakdown.items(), key=lambda item: item[1], reverse=True)[:3]
    for key, value in top_dimensions:
        if value < 0.68:
            continue
        label, tag = dimension_labels.get(key, ("综合质量较好", "quality"))
        parts.append(label)
        tags.append(tag)
    if candidate.provider:
        tags.append(candidate.provider)
    summary_text = rationale or strength
    if summary_text:
        parts.append(summary_text[:64])
    return "；".join(dict.fromkeys(parts)) or "综合评分较高", list(dict.fromkeys(tags))


# ---------------------------------------------------------------------------
# 核心评分流程
# ---------------------------------------------------------------------------

async def _score_candidates(model, state: SearchGraphState, *, mode: str) -> tuple[list[SearchCandidate], str, bool]:
    from app.modules.agent.search.utils import _match_preferred_site

    candidate_cap = _SCORE_CANDIDATE_CAP_BY_MODE.get(mode, 18)
    candidates = state.get("recall_candidates", [])[:candidate_cap]
    if not candidates:
        return [], "no_candidates", False

    llm_disabled_for_session = bool((state.get("debug") or {}).get("llmScoreUnavailable"))
    llm_failed = False
    if llm_disabled_for_session:
        llm_scores: dict[int, dict[str, Any]] = {}
        llm_failed = True
    else:
        llm_scores, llm_failed = await _llm_score_candidates(
            model,
            query=state["query"],
            task_spec=state["task_spec"],
            candidates=candidates,
            notebook_summaries=state.get("notebook_article_summaries", []),
        )
    if model is None:
        score_mode = "rule_only_no_model"
    elif llm_disabled_for_session:
        score_mode = "rule_only_llm_unavailable_session"
    elif not llm_scores:
        score_mode = "rule_only_llm_failed"
    elif len(llm_scores) < len(candidates):
        score_mode = "hybrid_partial_llm"
    else:
        score_mode = "hybrid_full_llm"

    scored: list[SearchCandidate] = []
    for index, candidate in enumerate(candidates):
        llm_item = llm_scores.get(index, {})
        authority_rule = _authority_score(candidate.domain)
        freshness_rule = _freshness_score(candidate.published_at, state["task_spec"].time_sensitivity)
        content_quality_rule = _content_quality_score(candidate)
        novelty_rule = _novelty_score(
            candidate=candidate,
            notebook_summaries=state.get("notebook_article_summaries", []),
        )
        preferred_match = _match_preferred_site(candidate.domain, state.get("preferred_sites", []))
        coverage = _coverage_score(
            candidate=candidate,
            preferred_match=bool(preferred_match or candidate.preferred_site_hit),
        )
        score_breakdown = {
            "relevance_score": round(_clamp(llm_item.get("relevance_score", 0.55)), 4),
            "authority_score": round(_blend_scores(_clamp(llm_item.get("authority_score", authority_rule)), authority_rule), 4),
            "coverage_score": coverage,
            "freshness_score": round(_blend_scores(_clamp(llm_item.get("freshness_score", freshness_rule)), freshness_rule), 4),
            "content_quality_score": round(_blend_scores(_clamp(llm_item.get("content_quality_score", content_quality_rule)), content_quality_rule), 4),
            "novelty_score": round(novelty_rule, 4),
        }
        final_score = _weighted_score(score_breakdown, state["task_spec"].score_weights)
        why_selected, reason_tags = _build_reasoning(
            candidate=candidate,
            score_breakdown=score_breakdown,
            rationale=llm_item.get("rationale", ""),
            strength=llm_item.get("strength", ""),
            preferred_site=preferred_match,
        )
        scored.append(candidate.model_copy(update={
            "preferred_site_hit": bool(preferred_match or candidate.preferred_site_hit),
            "score_breakdown": score_breakdown,
            "final_score": final_score,
            "why_selected": why_selected,
            "selected_reason_tags": reason_tags,
            "duplicate_risk": novelty_rule < 0.42,
        }))
    scored.sort(key=lambda item: item.final_score, reverse=True)
    if score_mode.startswith("rule_only"):
        logger.info("search.score_rule_mode", candidate_count=len(scored), mode=score_mode)
    return scored, score_mode, bool(llm_disabled_for_session or llm_failed)


def _select_candidates(
    scored: list[SearchCandidate],
    *,
    target_count: int,
    mode: str,
    task_spec: SearchTaskSpec,
) -> list[SearchCandidate]:
    from app.modules.agent.search.utils import _normalize_url

    if not scored or target_count <= 0:
        return []
    threshold = _SELECTION_THRESHOLD_BY_MODE.get(mode, 0.6)
    filtered = [candidate for candidate in scored if candidate.final_score >= threshold]
    pool = filtered or scored[: max(target_count * 2, target_count)]
    selected: list[SearchCandidate] = []
    selected_urls: set[str] = set()
    selected_domains: set[str] = set()

    def _append(candidate: SearchCandidate) -> bool:
        normalized_url = _normalize_url(candidate.url) or candidate.url
        if not normalized_url or normalized_url in selected_urls:
            return False
        selected.append(candidate)
        selected_urls.add(normalized_url)
        if candidate.domain:
            selected_domains.add(candidate.domain)
        return True

    # Guardrail 1: guarantee at least one strong-authority source when available.
    high_authority = next(
        (candidate for candidate in pool if candidate.score_breakdown.get("authority_score", 0.0) >= 0.8),
        None,
    )
    if high_authority is not None:
        _append(high_authority)

    # Guardrail 2: time-sensitive queries should include at least one fresh source when available.
    if task_spec.time_sensitivity == "high":
        fresh_candidate = next(
            (
                candidate
                for candidate in pool
                if candidate.score_breakdown.get("freshness_score", 0.0) >= 0.78
                and (_normalize_url(candidate.url) or candidate.url) not in selected_urls
            ),
            None,
        )
        if fresh_candidate is not None:
            _append(fresh_candidate)

    # Guardrail 3: try to diversify domains in first slots to avoid near-duplicate slates.
    diversity_target = min(target_count, 3)
    for candidate in pool:
        if len(selected) >= diversity_target:
            break
        if candidate.domain and candidate.domain in selected_domains:
            continue
        _append(candidate)

    for candidate in pool:
        if len(selected) >= target_count:
            break
        _append(candidate)

    if len(selected) < target_count:
        for candidate in scored:
            if len(selected) >= target_count:
                break
            _append(candidate)

    return selected[:target_count]


# ---------------------------------------------------------------------------
# LLM 评分
# ---------------------------------------------------------------------------

async def _llm_score_candidates(
    model,
    *,
    query: str,
    task_spec: SearchTaskSpec,
    candidates: list[SearchCandidate],
    notebook_summaries: list[dict[str, str]],
) -> tuple[dict[int, dict[str, Any]], bool]:
    if model is None:
        return {}, False
    scoring_model = model.bind(max_tokens=1800, temperature=0)
    summary_context = "\n".join(
        f"- {_safe_text(item.get('title')) or 'Untitled'}: {_safe_text(item.get('summaryText'))[:80]}"
        for item in notebook_summaries[:6]
    )
    all_scores: dict[int, dict[str, Any]] = {}
    batch_size = 20
    request_timeout_seconds = max(get_settings().lite_llm_timeout, 15)
    llm_unavailable = False

    system_msg = SystemMessage(content=_SCORE_SYSTEM_PROMPT)

    for offset in range(0, len(candidates), batch_size):
        if llm_unavailable:
            break
        batch = candidates[offset: offset + batch_size]
        human_msg = _build_score_human_message(
            query=query,
            task_spec=task_spec,
            summary_context=summary_context,
            candidates=batch,
        )
        try:
            structured_model = scoring_model.with_structured_output(
                _ScoreBatchOutput,
                method="function_calling",
            )
            batch_t0 = perf_counter()
            output = await asyncio.wait_for(
                structured_model.ainvoke([system_msg, human_msg]),
                timeout=request_timeout_seconds,
            )
            batch_ms = _elapsed_ms(batch_t0)
            for item in output.items:
                all_scores[offset + item.index] = item.model_dump()
            logger.info(
                "search.llm_score_batch_done",
                offset=offset,
                batch_size=len(batch),
                scored_count=len(output.items),
                duration_ms=batch_ms,
            )
        except Exception as exc:
            batch_ms = _elapsed_ms(batch_t0)
            if offset == 0 and len(batch) > 4:
                logger.info(
                    "search.llm_score_batch_retry",
                    offset=offset,
                    original_batch_size=len(batch),
                    duration_ms=batch_ms,
                    error=str(exc)[:120],
                )
                retry_ok = await _retry_batch_halved(
                    scoring_model, system_msg=system_msg, query=query,
                    task_spec=task_spec, summary_context=summary_context,
                    candidates=batch, offset=offset, all_scores=all_scores,
                    timeout=request_timeout_seconds,
                )
                if not retry_ok:
                    llm_unavailable = True
            else:
                logger.warning(
                    "search.llm_score_batch_failed",
                    offset=offset,
                    timeout_seconds=request_timeout_seconds,
                    error=str(exc)[:240],
                )
                llm_unavailable = True
    return all_scores, llm_unavailable


def _build_score_human_message(
    *,
    query: str,
    task_spec: SearchTaskSpec,
    summary_context: str,
    candidates: list[SearchCandidate],
) -> HumanMessage:
    candidate_lines = _format_candidate_lines(candidates)
    time_hint = {"high": "高（请优先考虑新内容）", "medium": "中", "low": "低"}.get(
        task_spec.time_sensitivity, task_spec.time_sensitivity,
    )
    return HumanMessage(content="\n".join([
        f"## 用户问题\n{query}",
        f"\n## 搜索意图\n- 搜索类型: {task_spec.search_type}\n- 时效要求: {time_hint}\n- 领域: {task_spec.domain_hint}",
        f"\n## 笔记本已有内容\n{summary_context or '（无）'}",
        f"\n## 候选结果（共 {len(candidates)} 条）\n" + "\n\n".join(candidate_lines),
    ]))


def _format_candidate_lines(batch: list[SearchCandidate]) -> list[str]:
    lines = []
    for idx, candidate in enumerate(batch):
        highlight_preview = _safe_text(" | ".join(candidate.highlights[:1]) or candidate.description)
        highlight_preview = re.sub(r"\s+", " ", highlight_preview).strip()[:320]
        published_info = ""
        if candidate.published_at:
            published_info = f"\npublished={candidate.published_at.strftime('%Y-%m-%d')}"
        lines.append(
            f"[{idx}] {candidate.title}\n"
            f"url={candidate.url}\n"
            f"domain={candidate.domain}{published_info}\n"
            f"highlights={highlight_preview}"
        )
    return lines


async def _retry_batch_halved(
    scoring_model,
    *,
    system_msg: SystemMessage,
    query: str,
    task_spec: SearchTaskSpec,
    summary_context: str,
    candidates: list[SearchCandidate],
    offset: int,
    all_scores: dict[int, dict[str, Any]],
    timeout: float,
) -> bool:
    mid = len(candidates) // 2
    halves = [candidates[:mid], candidates[mid:]]
    ok = False
    for hi, half in enumerate(halves):
        if not half:
            continue
        human_msg = _build_score_human_message(
            query=query,
            task_spec=task_spec,
            summary_context=summary_context,
            candidates=half,
        )
        try:
            structured_model = scoring_model.with_structured_output(
                _ScoreBatchOutput,
                method="function_calling",
            )
            output = await asyncio.wait_for(
                structured_model.ainvoke([system_msg, human_msg]),
                timeout=timeout,
            )
            base_offset = offset + (hi * mid)
            for item in output.items:
                all_scores[base_offset + item.index] = item.model_dump()
            ok = True
        except Exception as exc:
            logger.warning(
                "search.llm_score_half_retry_failed",
                half_index=hi,
                error=str(exc)[:120],
            )
    return ok
