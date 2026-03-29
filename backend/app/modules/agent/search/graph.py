"""基于 LangGraph 的搜索编排。"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal
from urllib.parse import urlparse

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest
from app.infra.providers.tavily.search_client import TavilySearchClient, TavilySearchRequest
from app.infra.telemetry.metrics import (
    observe_search_authority_proxy,
    observe_search_dedup,
    observe_search_diversity_proxy,
    observe_search_empty_slate,
    observe_search_novelty_proxy,
    observe_search_partial_failure,
    observe_search_stage,
)
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search.state import (
    SearchCandidate,
    SearchGraphState,
    SearchQueryPlan,
    SearchResponsePayload,
    SearchResultCardView,
    SearchRunView,
    SearchTaskSpec,
)

logger = structlog.get_logger(__name__)

_DEFAULT_SCORE_WEIGHTS = {
    "relevance_score": 0.34,
    "authority_score": 0.18,
    "coverage_score": 0.14,
    "freshness_score": 0.14,
    "content_quality_score": 0.12,
    "novelty_score": 0.08,
}
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
_MAX_ROUNDS_BY_MODE = {"fast": 2, "auto": 3, "deep": 3}
_MAX_PROVIDER_CALLS_PER_SEARCH = 6
_INTENT_ANALYSIS_TIMEOUT_BY_MODE = {"fast": 4.5, "auto": 6.0, "deep": 8.0}
_SCORE_CANDIDATE_CAP_BY_MODE = {"fast": 12, "auto": 18, "deep": 24}
_SELECTION_THRESHOLD_BY_MODE = {"fast": 0.58, "auto": 0.6, "deep": 0.62}
_TAVILY_DISABLE_KEYWORDS = (
    "quota",
    "credit",
    "credits",
    "insufficient",
    "usage limit",
    "payment required",
    "rate limit",
    "too many requests",
    "429",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "auth",
)
_TAVILY_DISABLE_SECONDS_BY_REASON = {
    "quota_exhausted": 1800,
    "auth_failed": 1800,
    "rate_limited": 300,
}
_TAVILY_PROVIDER_ERROR_STREAK_THRESHOLD = 3
_TAVILY_PROVIDER_ERROR_DISABLE_SECONDS = 180
_TAVILY_CIRCUIT: dict[str, Any] = {
    "disabled_until": None,
    "reason": "",
    "failure_streak": 0,
}


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _get_tavily_circuit_state() -> tuple[bool, str]:
    now = datetime.now(UTC)
    disabled_until = _TAVILY_CIRCUIT.get("disabled_until")
    reason = _safe_text(_TAVILY_CIRCUIT.get("reason"))
    if isinstance(disabled_until, datetime):
        if disabled_until > now:
            return True, reason or "provider_disabled"
        _TAVILY_CIRCUIT["disabled_until"] = None
        _TAVILY_CIRCUIT["reason"] = ""
    return False, ""


def _record_tavily_success() -> None:
    _TAVILY_CIRCUIT["failure_streak"] = 0


def _record_tavily_failure(reason: str) -> bool:
    reason = _safe_text(reason) or "provider_error"
    streak = int(_TAVILY_CIRCUIT.get("failure_streak") or 0) + 1
    _TAVILY_CIRCUIT["failure_streak"] = streak

    disable_seconds = int(_TAVILY_DISABLE_SECONDS_BY_REASON.get(reason, 0))
    if reason == "provider_error" and streak >= _TAVILY_PROVIDER_ERROR_STREAK_THRESHOLD:
        disable_seconds = _TAVILY_PROVIDER_ERROR_DISABLE_SECONDS
    if disable_seconds <= 0:
        return False

    _TAVILY_CIRCUIT["disabled_until"] = datetime.now(UTC) + timedelta(seconds=disable_seconds)
    _TAVILY_CIRCUIT["reason"] = reason
    return True


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_highlights(values: Any, *, limit: int = 3) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        text = _safe_text(value)
        if text:
            normalized.append(text)
    return normalized[:limit]


class _TaskSpecOutput(BaseModel):
    search_type: Literal["opinionated", "objective_fact", "exploratory", "comparison", "primary_source", "news_sensitive"] = "exploratory"
    content_depth: Literal["overview", "detail", "mixed"] = "mixed"
    time_sensitivity: Literal["low", "medium", "high"] = "medium"
    authority_preference: Literal["low", "medium", "high"] = "high"
    novelty_requirement: Literal["low", "medium", "high"] = "medium"
    domain_hint: str = "general"
    rewritten_query: str
    query_plans: list[SearchQueryPlan] = Field(default_factory=list)
    score_weights: dict[str, float] = Field(default_factory=dict)


class _ScoreItem(BaseModel):
    index: int
    relevance_score: float = Field(ge=0, le=1)
    authority_score: float = Field(ge=0, le=1)
    freshness_score: float = Field(ge=0, le=1)
    content_quality_score: float = Field(ge=0, le=1)
    rationale: str = ""


class _ScoreBatchOutput(BaseModel):
    items: list[_ScoreItem] = Field(default_factory=list)


async def run_search_agent(
    chat_model,
    lite_model,
    *,
    query: str,
    notebook_id: str,
    exa_api_key: str | None,
    tavily_api_key: str | None,
    mode: str = "auto",
    notebook_title: str = "",
    existing_article_urls: list[str] | None = None,
    notebook_article_summaries: list[dict[str, str]] | None = None,
    preferred_sites: list[str] | None = None,
    max_results: int = 10,
    search_session_id: str = "",
) -> SearchResponsePayload:
    """执行 LangGraph 搜索编排。"""

    graph = _build_search_graph(
        intent_model=chat_model,
        scoring_model=lite_model or chat_model,
    )
    started_at = perf_counter()
    state = await graph.ainvoke({
        "query": query.strip(),
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "mode": mode,
        "max_results": max_results,
        "target_count": min(max_results, 10),
        "max_rounds": _MAX_ROUNDS_BY_MODE.get(mode, 3),
        "current_round": 1,
        "existing_article_urls": existing_article_urls or [],
        "notebook_article_summaries": notebook_article_summaries or [],
        "preferred_sites": preferred_sites or [],
        "exa_api_key": exa_api_key,
        "tavily_api_key": tavily_api_key,
        "seen_urls": [_normalize_url(url) for url in (existing_article_urls or []) if url],
        "recall_candidates": [],
        "selected_candidates": [],
        "recall_summary": {},
        "provider_call_budget": _MAX_PROVIDER_CALLS_PER_SEARCH,
        "provider_calls_used": 0,
        "provider_call_counts": {"exa": 0, "tavily": 0},
        "tavily_disabled": False,
        "tavily_disable_reason": "",
        "forced_include_domains": _extract_query_site_domains(query),
        "debug": {},
    })

    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    return _build_response_payload(
        state=state,
        search_session_id=search_session_id,
        elapsed_ms=elapsed_ms,
    )


def _build_search_graph(*, intent_model, scoring_model):
    async def intent_analysis_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        with start_span("search.intent_analysis", attributes={"search.mode": mode}):
            task_spec = await _analyze_task_spec(
                intent_model,
                query=state["query"],
                mode=mode,
                notebook_title=state["notebook_title"],
                notebook_summaries=state.get("notebook_article_summaries", []),
            )
            observe_search_stage(stage="intent_analysis", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
            return {"task_spec": task_spec}

    async def recall_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        round_no = state["current_round"]
        with start_span("search.recall", attributes={"search.mode": mode, "search.round": round_no}):
            query_plan = _plan_for_round(
                task_spec=state["task_spec"],
                round_no=round_no,
                existing_article_urls=state.get("existing_article_urls", []),
                recall_candidates=state.get("recall_candidates", []),
                forced_include_domains=state.get("forced_include_domains", []),
            )
            forced_domains = list(state.get("forced_include_domains") or [])
            provider_call_budget = int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH)
            provider_calls_used = int(state.get("provider_calls_used") or 0)
            provider_call_counts = dict(state.get("provider_call_counts") or {"exa": 0, "tavily": 0})
            tavily_disabled = bool(state.get("tavily_disabled"))
            tavily_disable_reason = _safe_text(state.get("tavily_disable_reason"))
            debug_payload = dict(state.get("debug", {}))
            provider_attempts_total = int(debug_payload.get("providerAttempts") or 0)
            provider_failures_total = int(debug_payload.get("providerFailures") or 0)
            provider_all_failed_seen = bool(debug_payload.get("providerAllFailed"))
            tavily_globally_disabled, tavily_global_reason = _get_tavily_circuit_state()
            if tavily_globally_disabled:
                tavily_disabled = True
                if not tavily_disable_reason:
                    tavily_disable_reason = tavily_global_reason
            budget_left = max(provider_call_budget - provider_calls_used, 0)

            tasks: list[Any] = []
            task_provider_tags: list[str] = []
            if state.get("exa_api_key") and budget_left > 0:
                tasks.append(
                    _search_with_exa(
                        exa_api_key=state.get("exa_api_key"),
                        mode=mode,
                        task_spec=state["task_spec"],
                        query_plan=query_plan,
                        include_domains=forced_domains or None,
                    ),
                )
                task_provider_tags.append("exa")
                provider_calls_used += 1
                provider_call_counts["exa"] = int(provider_call_counts.get("exa", 0)) + 1
                budget_left -= 1
            if state.get("tavily_api_key") and budget_left > 0 and not tavily_disabled:
                tasks.append(
                    _search_with_tavily(
                        tavily_api_key=state.get("tavily_api_key"),
                        mode=mode,
                        task_spec=state["task_spec"],
                        query_plan=query_plan,
                        include_domains=forced_domains or None,
                    ),
                )
                task_provider_tags.append("tavily")
                provider_calls_used += 1
                provider_call_counts["tavily"] = int(provider_call_counts.get("tavily", 0)) + 1
                budget_left -= 1

            if not tasks:
                observe_search_stage(stage="recall", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
                return {
                    "provider_calls_used": provider_calls_used,
                    "provider_call_counts": provider_call_counts,
                    "tavily_disabled": tavily_disabled,
                    "tavily_disable_reason": tavily_disable_reason,
                    "recall_summary": {
                        "currentRound": round_no,
                        "candidateCount": len(state.get("recall_candidates", [])),
                        "selectedCount": len(state.get("selected_candidates", [])),
                        "providerCounts": provider_call_counts,
                        "providerCallsUsed": provider_calls_used,
                        "providerCallBudget": provider_call_budget,
                        "forcedIncludeDomains": forced_domains,
                        "queryPlan": query_plan.model_dump(),
                        "tavilyDisabled": tavily_disabled,
                        "tavilyDisableReason": tavily_disable_reason,
                    },
                    "debug": {
                        **debug_payload,
                        "providerAttempts": provider_attempts_total,
                        "providerFailures": provider_failures_total,
                        "providerAllFailed": provider_all_failed_seen,
                        "tavilyDisabled": tavily_disabled,
                        "tavilyDisableReason": tavily_disable_reason,
                    },
                }

            results = await asyncio.gather(*tasks, return_exceptions=True)
            new_candidates: list[SearchCandidate] = []
            failure_count = 0
            provider_attempts = len(task_provider_tags)
            tavily_disabled_next = tavily_disabled
            tavily_disable_reason_next = tavily_disable_reason
            for provider_tag, result in zip(task_provider_tags, results, strict=False):
                if isinstance(result, list):
                    if provider_tag == "tavily":
                        _record_tavily_success()
                    for item in result:
                        new_candidates.append(item.model_copy(update={"recall_round": round_no}))
                elif isinstance(result, Exception):
                    failure_count += 1
                    logger.warning("search.recall_task_failed", provider=provider_tag, error=str(result)[:200])
                    if provider_tag == "tavily":
                        disable_reason = _classify_tavily_failure(result)
                        if disable_reason:
                            tavily_disabled_next = True
                            tavily_disable_reason_next = disable_reason
                            globally_disabled = _record_tavily_failure(disable_reason)
                            logger.warning(
                                "search.tavily_disabled_for_session",
                                reason=disable_reason,
                                globally_disabled=globally_disabled,
                                error=str(result)[:200],
                            )
            provider_all_failed = provider_attempts > 0 and failure_count >= provider_attempts
            provider_attempts_total += provider_attempts
            provider_failures_total += failure_count
            provider_all_failed_seen = provider_all_failed_seen or provider_all_failed

            if failure_count > 0 and new_candidates:
                observe_search_partial_failure(mode=mode)

            existing_count = len(state.get("recall_candidates", []))
            merged_candidates, seen_urls = _merge_candidates(
                existing=state.get("recall_candidates", []),
                seen_urls=set(state.get("seen_urls", [])),
                new_candidates=new_candidates,
            )
            dedup_count = len(new_candidates) - (len(merged_candidates) - existing_count)
            if dedup_count > 0:
                observe_search_dedup(mode=mode, dedup_type="url_canonicalize", count=dedup_count)

            observe_search_stage(stage="recall", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
            return {
                "recall_candidates": merged_candidates,
                "seen_urls": sorted(seen_urls),
                "provider_calls_used": provider_calls_used,
                "provider_call_counts": provider_call_counts,
                "tavily_disabled": tavily_disabled_next,
                "tavily_disable_reason": tavily_disable_reason_next,
                "recall_summary": {
                    "currentRound": round_no,
                    "candidateCount": len(merged_candidates),
                    "selectedCount": len(state.get("selected_candidates", [])),
                    "providerCounts": provider_call_counts,
                    "providerCallsUsed": provider_calls_used,
                    "providerCallBudget": provider_call_budget,
                    "forcedIncludeDomains": forced_domains,
                    "queryPlan": query_plan.model_dump(),
                    "providerAttempts": provider_attempts,
                    "providerFailures": failure_count,
                    "providerAllFailed": provider_all_failed,
                    "providerAttemptsTotal": provider_attempts_total,
                    "providerFailuresTotal": provider_failures_total,
                    "tavilyDisabled": tavily_disabled_next,
                    "tavilyDisableReason": tavily_disable_reason_next,
                },
                "debug": {
                    **debug_payload,
                    "providerAttempts": provider_attempts_total,
                    "providerFailures": provider_failures_total,
                    "providerAllFailed": provider_all_failed_seen,
                    "tavilyDisabled": tavily_disabled_next,
                    "tavilyDisableReason": tavily_disable_reason_next,
                },
            }

    async def score_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        with start_span("search.score", attributes={"search.mode": mode, "search.candidate_count": len(state.get("recall_candidates", []))}):
            scored, score_mode, llm_score_unavailable = await _score_candidates(scoring_model, state, mode=mode)
            target_count = state["target_count"]
            selected = _select_candidates(
                scored,
                target_count=target_count,
                mode=mode,
                task_spec=state["task_spec"],
            )
            observe_search_stage(stage="score", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
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

    async def expand_recall_node(state: SearchGraphState) -> dict[str, Any]:
        observe_search_stage(stage="expand_recall", mode=state["mode"], status="ok", duration_ms=0)
        return {"current_round": state["current_round"] + 1}

    async def finalize_node(state: SearchGraphState) -> dict[str, Any]:
        mode = state["mode"]
        selected = state.get("selected_candidates") or state.get("recall_candidates", [])
        top = selected[:10]

        if top:
            authority_count = sum(1 for c in top if c.score_breakdown.get("authority_score", 0) >= 0.8)
            observe_search_authority_proxy(mode=mode, ratio=authority_count / len(top))

            unique_domains = len({c.domain for c in top})
            observe_search_diversity_proxy(mode=mode, entropy=unique_domains / len(top))

            novel_count = sum(1 for c in top if c.score_breakdown.get("novelty_score", 0) >= 0.5)
            observe_search_novelty_proxy(mode=mode, ratio=novel_count / len(top))
        else:
            observe_search_empty_slate(mode=mode, reason="no_above_threshold")

        observe_search_stage(stage="finalize", mode=mode, status="ok", duration_ms=0)
        return {"debug": {
            **state.get("debug", {}),
            "finalCandidateCount": len(state.get("recall_candidates", [])),
            "finalSelectedCount": len(state.get("selected_candidates", [])),
            "providerCallsUsed": int(state.get("provider_calls_used") or 0),
            "providerCallBudget": int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH),
            "providerCallCounts": dict(state.get("provider_call_counts") or {}),
        }}

    def decide_next_step(state: SearchGraphState) -> Literal["expand_recall", "finalize"]:
        selected_count = len(state.get("selected_candidates", []))
        candidate_count = len(state.get("recall_candidates", []))
        if selected_count >= state["target_count"]:
            return "finalize"
        if state["current_round"] >= state["max_rounds"]:
            return "finalize"
        if int(state.get("provider_calls_used") or 0) >= int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH):
            return "finalize"
        if bool((state.get("recall_summary") or {}).get("providerAllFailed")):
            return "finalize"
        if candidate_count >= 50:
            return "finalize"
        return "expand_recall"

    builder = StateGraph(SearchGraphState)
    builder.add_node("intent_analysis", intent_analysis_node)
    builder.add_node("recall", recall_node)
    builder.add_node("score", score_node)
    builder.add_node("expand_recall", expand_recall_node)
    builder.add_node("finalize", finalize_node)
    builder.add_edge(START, "intent_analysis")
    builder.add_edge("intent_analysis", "recall")
    builder.add_edge("recall", "score")
    builder.add_conditional_edges(
        "score",
        decide_next_step,
        {
            "expand_recall": "expand_recall",
            "finalize": "finalize",
        },
    )
    builder.add_edge("expand_recall", "recall")
    builder.add_edge("finalize", END)
    return builder.compile()


def _build_exclude_domains(existing_article_urls: list[str]) -> list[str]:
    domains: list[str] = []
    for url in existing_article_urls:
        domain = _domain_from_url(url)
        if domain:
            domains.append(domain)
    return list(dict.fromkeys(domains))


def _build_tavily_exclude_paths(existing_article_urls: list[str]) -> list[str]:
    paths: list[str] = []
    for url in existing_article_urls:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            continue
        if not parsed.path:
            continue
        normalized_path = parsed.path.rstrip("/") or "/"
        paths.append(rf"^{re.escape(normalized_path)}/?$")
    return list(dict.fromkeys(paths))


def _resolve_exa_max_age_hours(task_spec: SearchTaskSpec) -> int | None:
    if task_spec.time_sensitivity == "high":
        return 24 * 7
    if task_spec.time_sensitivity == "medium":
        return 24 * 30
    return None


def _resolve_tavily_time_range(task_spec: SearchTaskSpec) -> str | None:
    if task_spec.time_sensitivity == "high":
        return "week"
    if task_spec.time_sensitivity == "medium":
        return "month"
    return None


def _resolve_provider_timeout_seconds(mode: str) -> float:
    if mode == "fast":
        return 8.0
    if mode == "deep":
        return 14.0
    return 11.0


async def _analyze_task_spec(
    model,
    *,
    query: str,
    mode: str,
    notebook_title: str,
    notebook_summaries: list[dict[str, str]],
) -> SearchTaskSpec:
    summary_lines = [
        f"- {_safe_text(item.get('title')) or 'Untitled'}: {_safe_text(item.get('summaryText'))[:160]}"
        for item in notebook_summaries[:8]
        if _safe_text(item.get("summaryText"))
    ]
    user_prompt = "\n".join([
        f"用户问题：{query}",
        f"Notebook 标题：{notebook_title or 'Untitled'}",
        "Notebook 已有摘要：",
        "\n".join(summary_lines) if summary_lines else "(none)",
    ])
    if model is None:
        return _fallback_task_spec(query, mode=mode)
    try:
        structured_model = model.with_structured_output(
            _TaskSpecOutput,
            method="function_calling",
        )
        timeout_seconds = _resolve_intent_timeout_seconds(mode)
        output = await asyncio.wait_for(
            structured_model.ainvoke([
                SystemMessage(content=(
                    "你是 research search planner。"
                    "需要把用户问题与 notebook 上下文转成结构化搜索计划。"
                    "请明确 search_type、content_depth、time_sensitivity，"
                    "并生成 rewritten_query 与 4-6 条 query_plans。"
                    "score_weights 只输出 relevance_score、authority_score、coverage_score、"
                    "freshness_score、content_quality_score、novelty_score 六项，值在 0-1。"
                )),
                HumanMessage(content=user_prompt),
            ]),
            timeout=timeout_seconds,
        )
        fallback_plans = _fallback_query_plans(
            query,
            search_type=output.search_type,
            time_sensitivity=output.time_sensitivity,
        )
        return SearchTaskSpec(
            search_type=output.search_type,
            content_depth=output.content_depth,
            time_sensitivity=output.time_sensitivity,
            authority_preference=output.authority_preference,
            novelty_requirement=output.novelty_requirement,
            domain_hint=output.domain_hint,
            rewritten_query=output.rewritten_query,
            query_plans=output.query_plans or fallback_plans,
            score_weights=_normalize_weights(output.score_weights or _DEFAULT_SCORE_WEIGHTS),
        )
    except TimeoutError:
        logger.warning(
            "search.intent_analysis_timeout",
            mode=mode,
            timeout_seconds=_resolve_intent_timeout_seconds(mode),
        )
        return _fallback_task_spec(query, mode=mode)
    except Exception:
        logger.warning("search.intent_analysis_fallback", exc_info=True)
        return _fallback_task_spec(query, mode=mode)


def _fallback_task_spec(query: str, *, mode: str = "auto") -> SearchTaskSpec:
    lowered = query.lower()
    if any(keyword in lowered for keyword in ["对比", "比较", "vs", "versus", "compare"]):
        search_type = "comparison"
    elif any(keyword in lowered for keyword in ["新闻", "latest", "today", "breaking", "动态"]):
        search_type = "news_sensitive"
    elif any(keyword in lowered for keyword in ["是什么", "what is", "define", "定义"]):
        search_type = "objective_fact"
    else:
        search_type = "exploratory"
    content_depth = "detail" if any(keyword in lowered for keyword in ["深入", "detail", "原理", "实现"]) else "mixed"
    high_time_signals = ["最新", "today", "newest", "近期", "最近", "本周", "本月"]
    has_year_hint = bool(re.search(r"\b20\d{2}\b", lowered))
    time_sensitivity = "high" if has_year_hint or any(keyword in lowered for keyword in high_time_signals) else "medium"
    if mode == "fast":
        content_depth = "overview"
    elif mode == "deep" and content_depth == "mixed":
        content_depth = "detail"
    return SearchTaskSpec(
        search_type=search_type,
        content_depth=content_depth,
        time_sensitivity=time_sensitivity,
        authority_preference="high",
        novelty_requirement="medium",
        domain_hint="general",
        rewritten_query=query,
        query_plans=_fallback_query_plans(
            query,
            search_type=search_type,
            time_sensitivity=time_sensitivity,
        ),
        score_weights=_default_weights_for(search_type, time_sensitivity),
    )


def _fallback_query_plans(
    query: str,
    *,
    search_type: str = "exploratory",
    time_sensitivity: str = "medium",
) -> list[SearchQueryPlan]:
    normalized_query = _safe_text(query)
    plans = [
        SearchQueryPlan(key="base", query=normalized_query, intent="base"),
        SearchQueryPlan(key="overview", query=f"{normalized_query} overview key points".strip(), intent="overview"),
        SearchQueryPlan(key="detail", query=f"{normalized_query} detailed analysis implementation".strip(), intent="detail"),
        SearchQueryPlan(key="authority", query=f"{normalized_query} official documentation report paper".strip(), intent="authority"),
    ]
    if search_type == "comparison":
        plans.append(
            SearchQueryPlan(key="compare", query=f"{normalized_query} comparison benchmark alternatives".strip(), intent="comparison"),
        )
    elif search_type == "objective_fact":
        plans.append(
            SearchQueryPlan(key="definition", query=f"{normalized_query} definition official reference".strip(), intent="definition"),
        )
    else:
        plans.append(
            SearchQueryPlan(key="novel", query=f"{normalized_query} case study practical lessons".strip(), intent="novelty"),
        )
    if time_sensitivity == "high":
        plans.append(SearchQueryPlan(key="fresh", query=f"{normalized_query} latest updates 2026".strip(), intent="fresh"))
    else:
        plans.append(SearchQueryPlan(key="fresh", query=f"{normalized_query} recent updates".strip(), intent="fresh"))
    return plans[:6]


def _resolve_intent_timeout_seconds(mode: str) -> float:
    return float(_INTENT_ANALYSIS_TIMEOUT_BY_MODE.get(mode, 6.0))


def _default_weights_for(search_type: str, time_sensitivity: str) -> dict[str, float]:
    weights = dict(_DEFAULT_SCORE_WEIGHTS)
    if search_type == "opinionated":
        weights["coverage_score"] += 0.06
        weights["novelty_score"] += 0.04
    if search_type == "objective_fact":
        weights["authority_score"] += 0.06
        weights["coverage_score"] -= 0.03
    if time_sensitivity == "high":
        weights["freshness_score"] += 0.1
        weights["authority_score"] -= 0.03
    return _normalize_weights(weights)


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    filtered = {
        key: max(float(value), 0.0)
        for key, value in raw.items()
        if key in _DEFAULT_SCORE_WEIGHTS
    }
    merged = {**_DEFAULT_SCORE_WEIGHTS, **filtered}
    total = sum(merged.values()) or 1.0
    return {key: round(value / total, 4) for key, value in merged.items()}


def _plan_for_round(
    *,
    task_spec: SearchTaskSpec,
    round_no: int,
    existing_article_urls: list[str],
    recall_candidates: list[SearchCandidate],
    forced_include_domains: list[str],
) -> SearchQueryPlan:
    exclude_domains = _build_exclude_domains(existing_article_urls)
    exclude_paths = _build_tavily_exclude_paths(existing_article_urls)
    fallback_plans = _fallback_query_plans(
        task_spec.rewritten_query,
        search_type=task_spec.search_type,
        time_sensitivity=task_spec.time_sensitivity,
    )
    base_query = _safe_text(task_spec.rewritten_query) or _safe_text((task_spec.query_plans[:1] or fallback_plans)[0].query)
    query = base_query
    intent = "base"
    if round_no >= 2:
        query, intent = _expand_query_for_round(
            base_query=base_query,
            task_spec=task_spec,
            round_no=round_no,
            recall_candidates=recall_candidates,
        )
    if forced_include_domains:
        site_suffix = " ".join(f"site:{domain}" for domain in forced_include_domains[:4])
        if site_suffix:
            query = f"{query} {site_suffix}".strip()

    return SearchQueryPlan(
        key=f"round_{round_no}",
        query=query,
        intent=intent,
        exclude_domains=exclude_domains,
        exclude_paths=exclude_paths,
    )


def _expand_query_for_round(
    *,
    base_query: str,
    task_spec: SearchTaskSpec,
    round_no: int,
    recall_candidates: list[SearchCandidate],
) -> tuple[str, str]:
    if not recall_candidates:
        return f"{base_query} overview analysis".strip(), "expand_bootstrap"

    authority_ratio = sum(1 for item in recall_candidates if _authority_score(item.domain) >= 0.8) / max(len(recall_candidates), 1)
    unique_domains = len({item.domain for item in recall_candidates if item.domain})
    fresh_ratio = sum(
        1
        for item in recall_candidates
        if _freshness_score(item.published_at, task_spec.time_sensitivity) >= 0.8
    ) / max(len(recall_candidates), 1)
    novelty_ratio = sum(
        1
        for item in recall_candidates
        if _clamp(item.score_breakdown.get("novelty_score", 0.5)) >= 0.65
    ) / max(len(recall_candidates), 1)

    intent_parts: list[str] = []
    query_parts: list[str] = [base_query]
    if authority_ratio < 0.35:
        query_parts.append("official documentation whitepaper")
        intent_parts.append("authority")
    if task_spec.time_sensitivity == "high" and fresh_ratio < 0.35:
        query_parts.append("latest updates 2026")
        intent_parts.append("freshness")
    if unique_domains <= max(2, len(recall_candidates) // 2):
        query_parts.append("independent comparison")
        intent_parts.append("coverage")
    if novelty_ratio < 0.4:
        query_parts.append("alternative perspectives")
        intent_parts.append("novelty")
    if round_no >= 3:
        query_parts.append("case study limitations")
        intent_parts.append("expand")

    query = " ".join(dict.fromkeys(query_parts)).strip()
    if query == base_query:
        query = f"{base_query} in-depth analysis round {round_no}".strip()
        intent_parts.append("stability_expand")
    return query, "_".join(dict.fromkeys(intent_parts)) or "expand"


async def _search_with_exa(
    *,
    exa_api_key: str | None,
    mode: str,
    task_spec: SearchTaskSpec,
    query_plan: SearchQueryPlan,
    include_domains: list[str] | None = None,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not exa_api_key:
        return []
    client = ExaSearchClient()
    try:
        result = await client.search(
            ExaSearchRequest(
                query=query_plan.query,
                mode="deep" if mode == "deep" else "auto",
                max_results=6 if mode == "deep" else 4,
                freshness_hours=_resolve_exa_max_age_hours(task_spec),
                include_domains=include_domains,
                exclude_domains=None if include_domains else (query_plan.exclude_domains or None),
                timeout_seconds=_resolve_provider_timeout_seconds(mode),
            ),
            api_key=exa_api_key,
        )
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for row in result.get("results", []):
        url = _safe_text(row.get("url"))
        if not url:
            continue
        domain = _domain_from_url(url)
        candidates.append(SearchCandidate(
            title=_safe_text(row.get("title")) or url,
            url=url,
            domain=domain,
            description=_safe_text(row.get("summary")) or _safe_text(row.get("description")),
            author=_safe_text(row.get("author")) or None,
            published_at=_parse_datetime(row.get("publishedDate")),
            highlights=_safe_highlights(row.get("highlights")),
            provider="exa",
            query_key=query_plan.key,
            preferred_site_hit=is_preferred,
        ))
    return candidates


async def _search_with_tavily(
    *,
    tavily_api_key: str | None,
    mode: str,
    task_spec: SearchTaskSpec,
    query_plan: SearchQueryPlan,
    include_domains: list[str] | None = None,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not tavily_api_key:
        return []
    client = TavilySearchClient()
    try:
        result = await client.search(
            TavilySearchRequest(
                query=query_plan.query,
                search_depth="advanced",
                max_results=4,
                include_domains=include_domains or [],
                exclude_domains=[] if include_domains else query_plan.exclude_domains,
                exclude_paths=query_plan.exclude_paths,
                time_range=_resolve_tavily_time_range(task_spec),
                include_raw_content=False,
                timeout_seconds=_resolve_provider_timeout_seconds(mode),
            ),
            api_key=tavily_api_key,
        )
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for row in result.get("results", []):
        url = _safe_text(row.get("url"))
        if not url:
            continue
        domain = _domain_from_url(url)
        content = _safe_text(row.get("content"))
        highlights = _tavily_content_to_highlights(content)
        candidates.append(SearchCandidate(
            title=_safe_text(row.get("title")) or url,
            url=url,
            domain=domain,
            description=content[:280],
            author=None,
            published_at=_parse_datetime(row.get("published_date")),
            highlights=highlights,
            provider="tavily",
            query_key=query_plan.key,
            preferred_site_hit=is_preferred,
        ))
    return candidates


def _tavily_content_to_highlights(content: str) -> list[str]:
    clean = re.sub(r"\s+", " ", content or "").strip()
    if not clean:
        return []
    chunks = [clean[i:i + 420] for i in range(0, min(len(clean), 840), 420)]
    return [chunk.strip() for chunk in chunks[:2] if chunk.strip()]


def _classify_tavily_failure(exc: Exception) -> str:
    text = _error_chain_text(exc)
    if not text:
        return "provider_error"
    if any(keyword in text for keyword in _TAVILY_DISABLE_KEYWORDS):
        if any(keyword in text for keyword in ("quota", "credit", "insufficient", "usage limit", "payment required")):
            return "quota_exhausted"
        if any(keyword in text for keyword in ("unauthorized", "forbidden", "invalid api key", "auth")):
            return "auth_failed"
        return "rate_limited"
    return "provider_error"


def _error_chain_text(exc: Exception, *, max_depth: int = 4) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    visited: set[int] = set()
    depth = 0
    while current is not None and depth < max_depth:
        marker = id(current)
        if marker in visited:
            break
        visited.add(marker)
        message = _safe_text(current)
        if message:
            parts.append(message)
        response = getattr(current, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                parts.append(f"status={status_code}")
            response_text = _safe_text(getattr(response, "text", ""))
            if response_text:
                parts.append(response_text[:240])
        current = current.__cause__ or current.__context__
        depth += 1
    return " | ".join(parts).lower()


def _merge_candidates(
    *,
    existing: list[SearchCandidate],
    seen_urls: set[str],
    new_candidates: list[SearchCandidate],
) -> tuple[list[SearchCandidate], set[str]]:
    merged = {_normalize_url(item.url): item for item in existing}
    for candidate in new_candidates:
        normalized = _normalize_url(candidate.url)
        if not normalized or normalized in seen_urls:
            continue
        if normalized in merged:
            current = merged[normalized]
            if _is_preferred_candidate(candidate, current):
                merged[normalized] = candidate
            continue
        duplicate_key = _find_semantic_duplicate_key(candidate, merged)
        if duplicate_key:
            current = merged[duplicate_key]
            if _is_preferred_candidate(candidate, current):
                merged[duplicate_key] = candidate
            seen_urls.add(normalized)
            continue
        merged[normalized] = candidate
        seen_urls.add(normalized)
    return list(merged.values()), seen_urls


def _is_preferred_candidate(left: SearchCandidate, right: SearchCandidate) -> bool:
    """同 URL 或近似语义候选冲突时，优先保留质量更高的结果。"""
    left_signal = _candidate_quality_signal(left)
    right_signal = _candidate_quality_signal(right)
    if abs(left_signal - right_signal) >= 0.08:
        return left_signal > right_signal
    return len(" ".join(left.highlights)) > len(" ".join(right.highlights))


def _candidate_quality_signal(candidate: SearchCandidate) -> float:
    authority = _authority_score(candidate.domain)
    content_depth = min(len(" ".join(candidate.highlights) or candidate.description) / 480.0, 1.0)
    recency = _freshness_score(candidate.published_at, "medium")
    provider_bonus = 0.05 if candidate.provider == "exa" else 0.03 if candidate.provider == "tavily" else 0.0
    return _clamp(authority * 0.45 + content_depth * 0.35 + recency * 0.2 + provider_bonus)


def _find_semantic_duplicate_key(candidate: SearchCandidate, merged: dict[str, SearchCandidate]) -> str | None:
    candidate_fp = _candidate_semantic_fingerprint(candidate)
    if not candidate_fp:
        return None
    for key, current in merged.items():
        current_fp = _candidate_semantic_fingerprint(current)
        if not current_fp:
            continue
        similarity = _token_similarity(candidate_fp, current_fp)
        if similarity >= 0.86:
            return key
    return None


def _candidate_semantic_fingerprint(candidate: SearchCandidate) -> str:
    title = _safe_text(candidate.title).lower()
    highlight = _safe_text(" ".join(candidate.highlights[:1]) or candidate.description).lower()
    return re.sub(r"\s+", " ", f"{title} {highlight}").strip()


async def _score_candidates(model, state: SearchGraphState, *, mode: str) -> tuple[list[SearchCandidate], str, bool]:
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
        coverage_score = _coverage_score(
            candidate=candidate,
            preferred_match=bool(preferred_match or candidate.preferred_site_hit),
        )
        score_breakdown = {
            "relevance_score": round(_clamp(llm_item.get("relevance_score", 0.55)), 4),
            "authority_score": round(_blend_scores(_clamp(llm_item.get("authority_score", authority_rule)), authority_rule), 4),
            "coverage_score": coverage_score,
            "freshness_score": round(_blend_scores(_clamp(llm_item.get("freshness_score", freshness_rule)), freshness_rule), 4),
            "content_quality_score": round(_blend_scores(_clamp(llm_item.get("content_quality_score", content_quality_rule)), content_quality_rule), 4),
            "novelty_score": round(novelty_rule, 4),
        }
        final_score = _weighted_score(score_breakdown, state["task_spec"].score_weights)
        why_selected, reason_tags = _build_reasoning(
            candidate=candidate,
            score_breakdown=score_breakdown,
            rationale=llm_item.get("rationale", ""),
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


def _coverage_score(*, candidate: SearchCandidate, preferred_match: bool) -> float:
    text = " ".join(candidate.highlights).strip() or candidate.description
    highlight_depth = min(len(text) / 260.0, 1.0)
    source_signal = 0.1 if candidate.provider in {"exa", "tavily"} else 0.0
    preferred_bonus = 0.2 if preferred_match else 0.0
    return round(_clamp(0.4 + highlight_depth * 0.3 + source_signal + preferred_bonus), 4)


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
    scoring_model = model.bind(max_tokens=700, temperature=0)
    summary_context = "\n".join(
        f"- {_safe_text(item.get('title')) or 'Untitled'}: {_safe_text(item.get('summaryText'))[:80]}"
        for item in notebook_summaries[:6]
    )
    all_scores: dict[int, dict[str, Any]] = {}
    batch_size = 8
    request_timeout_seconds = 10
    llm_unavailable = False
    for offset in range(0, len(candidates), batch_size):
        if llm_unavailable:
            break
        batch = candidates[offset: offset + batch_size]
        candidate_lines = []
        for idx, candidate in enumerate(batch):
            highlight_preview = _safe_text(" | ".join(candidate.highlights[:1]) or candidate.description)
            highlight_preview = re.sub(r"\s+", " ", highlight_preview).strip()[:320]
            candidate_lines.append(
                f"[{idx}] {candidate.title}\n"
                f"url={candidate.url}\n"
                f"domain={candidate.domain}\n"
                f"provider={candidate.provider}\n"
                f"highlights={highlight_preview}"
            )
        try:
            structured_model = scoring_model.with_structured_output(
                _ScoreBatchOutput,
                method="function_calling",
            )
            output = await asyncio.wait_for(
                structured_model.ainvoke([
                    SystemMessage(content=(
                        "你是搜索结果评分器。"
                        "请根据用户问题和候选摘要，对每个候选输出 relevance_score、authority_score、"
                        "freshness_score、content_quality_score 与简短 rationale。"
                        "评分范围为 0-1。不要遗漏任何 index。"
                    )),
                    HumanMessage(content="\n".join([
                        f"query={query}",
                        f"task_spec={task_spec.model_dump_json()}",
                        f"notebook_summaries={summary_context or '(none)'}",
                        "candidates:",
                        "\n\n".join(candidate_lines),
                    ])),
                ]),
                timeout=request_timeout_seconds,
            )
            for item in output.items:
                all_scores[offset + item.index] = item.model_dump()
        except Exception as exc:
            logger.warning(
                "search.llm_score_batch_failed",
                offset=offset,
                timeout_seconds=request_timeout_seconds,
                error=str(exc)[:240],
                exc_info=True,
            )
            llm_unavailable = True
    return all_scores, llm_unavailable


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
    if rationale:
        parts.append(rationale[:64])
    return "；".join(dict.fromkeys(parts)) or "综合评分较高", list(dict.fromkeys(tags))


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


def _match_preferred_site(domain: str, preferred_sites: list[str]) -> str | None:
    lowered = domain.lower()
    for site in preferred_sites:
        if site and site in lowered:
            return site
    return None


def _blend_scores(primary: float, rule_score: float) -> float:
    return round(_clamp(primary * 0.7 + rule_score * 0.3), 4)


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", left))
    right_tokens = set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", right))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens) or 1
    return intersection / union


def _build_response_payload(
    *,
    state: SearchGraphState,
    search_session_id: str,
    elapsed_ms: float,
) -> SearchResponsePayload:
    target_count = state["target_count"]
    candidates = state.get("selected_candidates") or state.get("recall_candidates", [])
    final_candidates = candidates[:target_count]
    items: list[SearchResultCardView] = []
    for idx, candidate in enumerate(final_candidates, start=1):
        preferred_match = _match_preferred_site(candidate.domain, state.get("preferred_sites", []))
        items.append(SearchResultCardView(
            id="",
            title=candidate.title,
            url=candidate.url,
            domain=candidate.domain,
            sourceName=candidate.domain,
            sourceTypeBadge=_source_type_badge(candidate.domain),
            authorityBadge=_authority_badge(candidate.score_breakdown.get("authority_score", 0.0)),
            publishedAt=candidate.published_at,
            description=candidate.description,
            author=candidate.author,
            highlights=candidate.highlights[:2],
            whySelected=candidate.why_selected,
            importSuggestion="duplicate_risk" if candidate.duplicate_risk else ("recommended" if candidate.final_score >= 0.72 else "optional"),
            finalScore=candidate.final_score,
            scoreBreakdown=candidate.score_breakdown,
            provider=candidate.provider,
            queryFamily=candidate.query_key,
            preferredSiteHit=bool(preferred_match or candidate.preferred_site_hit),
            matchedPreferredSite=preferred_match,
            duplicateRisk=candidate.duplicate_risk,
            selectedReasonTags=candidate.selected_reason_tags,
            faviconUrl=f"https://www.google.com/s2/favicons?domain={candidate.domain}&sz=64" if candidate.domain else None,
            displayRank=idx,
        ))
    return SearchResponsePayload(
        run=SearchRunView(
            id=search_session_id,
            notebookId=state["notebook_id"],
            query=state["query"],
            mode=state["mode"],
            modeLabel=_mode_label(state["mode"]),
            status="completed",
            currentRound=state["current_round"],
            maxRounds=state["max_rounds"],
            targetCount=target_count,
            elapsedMs=elapsed_ms,
        ),
        taskSpec=state["task_spec"].model_dump(),
        recallSummary=state.get("recall_summary", {}),
        items=items,
        preferencesApplied={
            "preferredSites": state.get("preferred_sites", []),
        },
        debug=state.get("debug"),
    )


def _mode_label(mode: str) -> str:
    if mode == "fast":
        return "Fast Research"
    if mode == "deep":
        return "Deep Research"
    return "Auto Research"


def _source_type_badge(domain: str) -> str:
    if any(token in domain for token in ["arxiv", "nature", "science", "acm", "springer"]):
        return "Paper"
    if domain.endswith(".gov") or domain.endswith(".edu"):
        return "Official"
    if "docs." in domain or "developer." in domain or "github.com" in domain:
        return "Docs"
    return "Web"


def _authority_badge(score: float) -> str | None:
    if score >= 0.88:
        return "High authority"
    if score >= 0.72:
        return "Trusted"
    return None


def _domain_from_url(url: str) -> str:
    parsed = urlparse(_safe_text(url))
    return parsed.netloc.lower().removeprefix("www.")


def _normalize_domain_token(raw: str) -> str:
    token = _safe_text(raw).lower()
    if not token:
        return ""
    token = token.removeprefix("site:")
    if "://" in token:
        parsed = urlparse(token)
        token = parsed.netloc or token
    token = token.split("/")[0].strip().strip(".,;:!?)]}>'\"")
    token = token.removeprefix("www.")
    if "." not in token:
        return ""
    return token


def _extract_query_site_domains(query: str) -> list[str]:
    matches = re.findall(r"(?:^|\s)site:([^\s]+)", (query or "").lower())
    domains: list[str] = []
    for raw in matches:
        normalized = _normalize_domain_token(raw)
        if normalized:
            domains.append(normalized)
    return list(dict.fromkeys(domains))


def _normalize_url(url: str) -> str:
    normalized = _safe_text(url).lower()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _clamp(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(float(value), 1.0))
