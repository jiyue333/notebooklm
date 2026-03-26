"""基于 LangGraph 的搜索编排。"""

from __future__ import annotations

import asyncio
import math
import re
from datetime import UTC, datetime
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
_ROUND_MULTIPLIER = {"fast": 2, "auto": 3, "deep": 4}


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


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
        "max_rounds": _ROUND_MULTIPLIER.get(mode, 3),
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
            query_plans = _plans_for_round(
                task_spec=state["task_spec"],
                round_no=round_no,
                existing_article_urls=state.get("existing_article_urls", []),
            )
            preferred_sites = state.get("preferred_sites", [])

            tasks: list = [
                _search_with_exa(
                    exa_api_key=state.get("exa_api_key"),
                    mode=mode,
                    task_spec=state["task_spec"],
                    query_plans=query_plans,
                ),
                _search_with_tavily(
                    tavily_api_key=state.get("tavily_api_key"),
                    task_spec=state["task_spec"],
                    query_plans=query_plans,
                ),
            ]

            # 偏好站点召回：仅 round 1 且用户配置了 preferred_sites 时执行
            if preferred_sites and round_no == 1:
                pref_plan = [SearchQueryPlan(
                    key="preferred_sites",
                    query=state["task_spec"].rewritten_query,
                    intent="preferred_sites",
                    exclude_paths=_build_tavily_exclude_paths(state.get("existing_article_urls", [])),
                )]
                tasks.extend([
                    _search_with_exa(
                        exa_api_key=state.get("exa_api_key"),
                        mode=mode,
                        task_spec=state["task_spec"],
                        query_plans=pref_plan,
                        include_domains=preferred_sites,
                        is_preferred=True,
                    ),
                    _search_with_tavily(
                        tavily_api_key=state.get("tavily_api_key"),
                        task_spec=state["task_spec"],
                        query_plans=pref_plan,
                        include_domains=preferred_sites,
                        is_preferred=True,
                    ),
                ])

            results = await asyncio.gather(*tasks, return_exceptions=True)
            new_candidates: list[SearchCandidate] = []
            failure_count = 0
            for result in results:
                if isinstance(result, list):
                    new_candidates.extend(result)
                elif isinstance(result, Exception):
                    failure_count += 1
                    logger.warning("search.recall_task_failed", error=str(result)[:200])

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

            exa_count = sum(1 for c in new_candidates if c.provider == "exa")
            tavily_count = sum(1 for c in new_candidates if c.provider == "tavily")
            observe_search_stage(stage="recall", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
            return {
                "recall_candidates": merged_candidates,
                "seen_urls": sorted(seen_urls),
                "recall_summary": {
                    "currentRound": round_no,
                    "candidateCount": len(merged_candidates),
                    "selectedCount": len(state.get("selected_candidates", [])),
                    "providerCounts": {
                        "exa": exa_count,
                        "tavily": tavily_count,
                    },
                },
            }

    async def score_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        with start_span("search.score", attributes={"search.mode": mode, "search.candidate_count": len(state.get("recall_candidates", []))}):
            scored = await _score_candidates(scoring_model, state)
            target_count = state["target_count"]
            selected = [candidate for candidate in scored if candidate.final_score >= 0.6][:target_count]
            observe_search_stage(stage="score", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
            return {
                "recall_candidates": scored,
                "selected_candidates": selected,
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
        }}

    def decide_next_step(state: SearchGraphState) -> Literal["expand_recall", "finalize"]:
        selected_count = len(state.get("selected_candidates", []))
        candidate_count = len(state.get("recall_candidates", []))
        if selected_count >= state["target_count"]:
            return "finalize"
        if state["current_round"] >= state["max_rounds"]:
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


async def _analyze_task_spec(
    model,
    *,
    query: str,
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
        return _fallback_task_spec(query)
    try:
        structured_model = model.with_structured_output(
            _TaskSpecOutput,
            method="function_calling",
        )
        output = await structured_model.ainvoke([
            SystemMessage(content=(
                "你是 research search planner。"
                "需要把用户问题与 notebook 上下文转成结构化搜索计划。"
                "请明确 search_type、content_depth、time_sensitivity，"
                "并生成 rewritten_query 与 4-6 条 query_plans。"
                "score_weights 只输出 relevance_score、authority_score、coverage_score、"
                "freshness_score、content_quality_score、novelty_score 六项，值在 0-1。"
            )),
            HumanMessage(content=user_prompt),
        ])
        return SearchTaskSpec(
            search_type=output.search_type,
            content_depth=output.content_depth,
            time_sensitivity=output.time_sensitivity,
            authority_preference=output.authority_preference,
            novelty_requirement=output.novelty_requirement,
            domain_hint=output.domain_hint,
            rewritten_query=output.rewritten_query,
            query_plans=output.query_plans or _fallback_query_plans(query),
            score_weights=_normalize_weights(output.score_weights or _DEFAULT_SCORE_WEIGHTS),
        )
    except Exception:
        logger.warning("search.intent_analysis_fallback", exc_info=True)
        return _fallback_task_spec(query)


def _fallback_task_spec(query: str) -> SearchTaskSpec:
    lowered = query.lower()
    search_type = "objective_fact" if any(keyword in lowered for keyword in ["是什么", "what is", "define", "定义"]) else "exploratory"
    content_depth = "detail" if any(keyword in lowered for keyword in ["深入", "detail", "原理", "实现"]) else "mixed"
    time_sensitivity = "high" if any(keyword in lowered for keyword in ["最新", "today", "2025", "2026", "newest"]) else "medium"
    return SearchTaskSpec(
        search_type=search_type,
        content_depth=content_depth,
        time_sensitivity=time_sensitivity,
        authority_preference="high",
        novelty_requirement="medium",
        domain_hint="general",
        rewritten_query=query,
        query_plans=_fallback_query_plans(query),
        score_weights=_default_weights_for(search_type, time_sensitivity),
    )


def _fallback_query_plans(query: str) -> list[SearchQueryPlan]:
    normalized_query = _safe_text(query)
    return [
        SearchQueryPlan(key="base", query=normalized_query, intent="base"),
        SearchQueryPlan(key="overview", query=f"{normalized_query} overview".strip(), intent="overview"),
        SearchQueryPlan(key="detail", query=f"{normalized_query} detailed analysis".strip(), intent="detail"),
        SearchQueryPlan(key="authority", query=f"{normalized_query} official documentation report paper".strip(), intent="authority"),
        SearchQueryPlan(key="fresh", query=f"{normalized_query} latest updates".strip(), intent="fresh"),
    ]


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


def _plans_for_round(
    *,
    task_spec: SearchTaskSpec,
    round_no: int,
    existing_article_urls: list[str],
) -> list[SearchQueryPlan]:
    base_plans = task_spec.query_plans[:5] or _fallback_query_plans(task_spec.rewritten_query)
    exclude_domains = _build_exclude_domains(existing_article_urls)
    exclude_paths = _build_tavily_exclude_paths(existing_article_urls)
    if round_no == 1:
        plans = base_plans[:4]
    elif round_no == 2:
        plans = base_plans
    else:
        plans = list(base_plans)
        plans.append(SearchQueryPlan(
            key=f"expand_{round_no}",
            query=f"{task_spec.rewritten_query} case study limitations",
            intent="expand",
        ))
    return [
        plan.model_copy(update={
            "exclude_domains": exclude_domains,
            "exclude_paths": exclude_paths,
        })
        for plan in plans
    ]


async def _search_with_exa(
    *,
    exa_api_key: str | None,
    mode: str,
    task_spec: SearchTaskSpec,
    query_plans: list[SearchQueryPlan],
    include_domains: list[str] | None = None,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not exa_api_key:
        return []
    client = ExaSearchClient()
    try:
        tasks = [
            client.search(
                ExaSearchRequest(
                    query=plan.query,
                    mode="deep" if mode == "deep" else "auto",
                    max_results=6 if mode == "deep" else 4,
                    freshness_hours=_resolve_exa_max_age_hours(task_spec),
                    include_domains=include_domains,
                    exclude_domains=None if include_domains else (plan.exclude_domains or None),
                ),
                api_key=exa_api_key,
            )
            for plan in query_plans
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for plan, result in zip(query_plans, results):
        if isinstance(result, Exception):
            logger.warning("search.exa_failed", query=plan.query, error=str(result)[:200])
            continue
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
                query_key=plan.key,
                preferred_site_hit=is_preferred,
            ))
    return candidates


async def _search_with_tavily(
    *,
    tavily_api_key: str | None,
    task_spec: SearchTaskSpec,
    query_plans: list[SearchQueryPlan],
    include_domains: list[str] | None = None,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not tavily_api_key:
        return []
    client = TavilySearchClient()
    try:
        tasks = [
            client.search(
                TavilySearchRequest(
                    query=plan.query,
                    search_depth="advanced",
                    max_results=4,
                    include_domains=include_domains or [],
                    exclude_domains=[] if include_domains else plan.exclude_domains,
                    exclude_paths=plan.exclude_paths,
                    time_range=_resolve_tavily_time_range(task_spec),
                    include_raw_content=False,
                ),
                api_key=tavily_api_key,
            )
            for plan in query_plans
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for plan, result in zip(query_plans, results):
        if isinstance(result, Exception):
            logger.warning("search.tavily_failed", query=plan.query, error=str(result)[:200])
            continue
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
                query_key=plan.key,
                preferred_site_hit=is_preferred,
            ))
    return candidates


def _tavily_content_to_highlights(content: str) -> list[str]:
    clean = re.sub(r"\s+", " ", content or "").strip()
    if not clean:
        return []
    chunks = [clean[i:i + 420] for i in range(0, min(len(clean), 840), 420)]
    return [chunk.strip() for chunk in chunks[:2] if chunk.strip()]


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
            if len(candidate.highlights) > len(current.highlights):
                merged[normalized] = candidate
            continue
        merged[normalized] = candidate
        seen_urls.add(normalized)
    return list(merged.values()), seen_urls


async def _score_candidates(model, state: SearchGraphState) -> list[SearchCandidate]:
    candidates = state.get("recall_candidates", [])[:50]
    if not candidates:
        return []

    llm_scores = await _llm_score_candidates(
        model,
        query=state["query"],
        task_spec=state["task_spec"],
        candidates=candidates,
        notebook_summaries=state.get("notebook_article_summaries", []),
    )

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
        score_breakdown = {
            "relevance_score": round(_clamp(llm_item.get("relevance_score", 0.55)), 4),
            "authority_score": round(_blend_scores(_clamp(llm_item.get("authority_score", authority_rule)), authority_rule), 4),
            "coverage_score": 1.0 if preferred_match else 0.6,
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
    return scored


async def _llm_score_candidates(
    model,
    *,
    query: str,
    task_spec: SearchTaskSpec,
    candidates: list[SearchCandidate],
    notebook_summaries: list[dict[str, str]],
) -> dict[int, dict[str, Any]]:
    if model is None:
        return {}
    summary_context = "\n".join(
        f"- {_safe_text(item.get('title')) or 'Untitled'}: {_safe_text(item.get('summaryText'))[:120]}"
        for item in notebook_summaries[:6]
    )
    all_scores: dict[int, dict[str, Any]] = {}
    batch_size = 12
    for offset in range(0, len(candidates), batch_size):
        batch = candidates[offset: offset + batch_size]
        candidate_lines = []
        for idx, candidate in enumerate(batch):
            candidate_lines.append(
                f"[{idx}] {candidate.title}\n"
                f"url={candidate.url}\n"
                f"domain={candidate.domain}\n"
                f"provider={candidate.provider}\n"
                f"highlights={' | '.join(candidate.highlights[:2]) or candidate.description[:180]}"
            )
        try:
            structured_model = model.with_structured_output(
                _ScoreBatchOutput,
                method="function_calling",
            )
            output = await structured_model.ainvoke([
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
            ])
            for item in output.items:
                all_scores[offset + item.index] = item.model_dump()
        except Exception:
            logger.warning("search.llm_score_batch_failed", offset=offset, exc_info=True)
    return all_scores


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
    if score_breakdown["authority_score"] >= 0.8:
        parts.append("来源权威")
        tags.append("authority")
    if score_breakdown["relevance_score"] >= 0.8:
        parts.append("与问题高度相关")
        tags.append("relevance")
    if score_breakdown["novelty_score"] >= 0.7:
        parts.append("能补充 notebook 新视角")
        tags.append("novelty")
    if score_breakdown["freshness_score"] >= 0.8:
        parts.append("时效性较好")
        tags.append("freshness")
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
