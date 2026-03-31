"""搜索编排入口：intent || recall 并行 → score → [expand_recall 循环] → finalize。"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from app.modules.agent.search.nodes.finalize import _build_response_payload, finalize_node
from app.modules.agent.search.nodes.intent import _build_rule_task_spec, build_rewritten_query, make_intent_node
from app.modules.agent.search.nodes.recall import _MAX_PROVIDER_CALLS_PER_SEARCH, make_recall_node
from app.modules.agent.search.nodes.score import make_score_node
from app.modules.agent.search.state import SearchResponsePayload
from app.modules.agent.search.utils import _extract_query_site_domains, _normalize_url

_MAX_ROUNDS_BY_MODE = {"fast": 1, "auto": 3, "deep": 3}


def _build_initial_state(
    *,
    query: str,
    notebook_id: str,
    notebook_title: str,
    mode: str,
    max_results: int,
    existing_article_urls: list[str] | None,
    notebook_article_summaries: list[dict[str, str]] | None,
    preferred_sites: list[str] | None,
    exa_api_key: str | None,
    tavily_api_key: str | None,
) -> dict[str, Any]:
    rewritten = build_rewritten_query(query)
    return {
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
        "task_spec": _build_rule_task_spec(query, mode=mode, rewritten_query=rewritten),
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
    }


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
    """执行搜索编排：所有模式 intent || recall 并行。"""

    initial_state = _build_initial_state(
        query=query,
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        mode=mode,
        max_results=max_results,
        existing_article_urls=existing_article_urls,
        notebook_article_summaries=notebook_article_summaries,
        preferred_sites=preferred_sites,
        exa_api_key=exa_api_key,
        tavily_api_key=tavily_api_key,
    )

    scoring_model = lite_model or chat_model
    started_at = perf_counter()

    state = await _run_pipeline(
        chat_model, scoring_model, initial_state=initial_state,
    )

    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    return _build_response_payload(
        state=state,
        search_session_id=search_session_id,
        elapsed_ms=elapsed_ms,
    )


async def _run_pipeline(
    intent_model,
    scoring_model,
    *,
    initial_state: dict[str, Any],
) -> dict[str, Any]:
    """统一 pipeline：intent || recall R1 并行 → score → [expand rounds] → finalize。

    Round 1: Exa + Tavily 都用 rewritten_query（规则生成，不等 LLM）。
    Round 2+: 用 intent LLM 生成的 query_plans 分配给两个 provider。
    """

    intent_node = make_intent_node(intent_model)
    recall_node = make_recall_node()
    score_node = make_score_node(scoring_model)

    intent_result, recall_result = await asyncio.gather(
        intent_node(initial_state),
        recall_node(initial_state),
    )

    state = {**initial_state, **recall_result, **intent_result}

    score_result = await score_node(state)
    state = {**state, **score_result}

    max_rounds = int(state.get("max_rounds") or 1)
    while _should_expand(state) and state["current_round"] < max_rounds:
        from app.infra.telemetry.metrics import observe_search_stage
        observe_search_stage(stage="expand_recall", mode=state["mode"], status="ok", duration_ms=0)
        state["current_round"] = state["current_round"] + 1

        recall_result = await recall_node(state)
        state = {**state, **recall_result}

        score_result = await score_node(state)
        state = {**state, **score_result}

    finalize_result = await finalize_node(state)
    return {**state, **finalize_result}


def _should_expand(state: dict[str, Any]) -> bool:
    selected_count = len(state.get("selected_candidates") or [])
    candidate_count = len(state.get("recall_candidates") or [])
    if selected_count >= state["target_count"]:
        return False
    if int(state.get("provider_calls_used") or 0) >= int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH):
        return False
    if bool((state.get("recall_summary") or {}).get("providerAllFailed")):
        return False
    if candidate_count >= 50:
        return False
    return True
