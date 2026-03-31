"""Chat LangGraph 编排。

flow: query_router → retrieval_planner → parallel_fetch(retrieval + web)
      → answer_generator → citation_verifier → END
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Awaitable, Callable
from typing import Any

import structlog
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_chat_error, observe_chat_stage
from app.modules.agent.chat.nodes import (
    answer_generator_node,
    citation_verifier_node,
    query_router_node,
    retrieval_engine_node,
    retrieval_planner_node,
    web_search_broker_node,
)
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec

logger = structlog.get_logger(__name__)


def _fallback_update(node_name: str, state: ChatGraphState) -> dict[str, Any]:
    route = state.get("route", "general")
    if node_name == "query_router":
        return {
            "route": "article_qa" if state.get("article_id") else "general",
            "retrieval_scope": "article" if state.get("article_id") else "none",
            "output_mode": "concise",
            "tools_needed": [],
            "router_need_web_search": False,
            "router_web_search_reason": "not_needed",
        }
    if node_name == "retrieval_planner":
        return {"retrieval_plan": RetrievalPlanSpec(strategy="skip")}
    if node_name == "retrieval_engine":
        return {"local_evidence": []}
    if node_name == "web_search_broker":
        return {
            "need_web_search": False,
            "web_search_reason": "timeout",
            "web_evidence": [],
        }
    if node_name == "parallel_fetch":
        fallback: dict[str, Any] = {}
        fallback.update(_fallback_update("retrieval_engine", state))
        fallback.update(_fallback_update("web_search_broker", state))
        return fallback
    if node_name == "answer_generator":
        return {
            "answer_text": "抱歉，本轮回答超时，请稍后重试或缩小问题范围。",
            "raw_citations": [],
        }
    if node_name == "citation_verifier":
        return {
            "verified_citations": [],
            "trace_log": {
                "route": route,
                "citation_count": 0,
                "invalid_citation_count": 0,
                "verification_timeout": True,
            },
        }
    return {}


def _resolve_node_timeout_seconds(state: ChatGraphState) -> float:
    settings = get_settings()
    base_seconds = max(settings.chat_node_timeout_ms / 1000, 0.05)
    deadline = state.get("deadline_monotonic")
    if not isinstance(deadline, (int, float)):
        return base_seconds
    remaining = float(deadline) - perf_counter() - 0.02
    if remaining <= 0:
        return 0.01
    return max(0.01, min(base_seconds, remaining))


def _with_node_timeout(
    node_name: str,
    node_fn: Callable[[ChatGraphState], Awaitable[dict[str, Any]]],
) -> Callable[[ChatGraphState], Awaitable[dict[str, Any]]]:
    async def _wrapped(state: ChatGraphState) -> dict[str, Any]:
        route = state.get("route", "general")
        timeout_seconds = _resolve_node_timeout_seconds(state)
        t_node = perf_counter()
        logger.debug("chat.node_start", node=node_name, route=route,
                     timeout_ms=round(timeout_seconds * 1000, 2))
        try:
            if timeout_seconds <= 0.011:
                raise asyncio.TimeoutError()
            result = await asyncio.wait_for(node_fn(state), timeout=timeout_seconds)
            duration_ms = round((perf_counter() - t_node) * 1000, 2)
            logger.info("chat.node_done", node=node_name, route=route, duration_ms=duration_ms)
            return result
        except asyncio.TimeoutError:
            duration_ms = round((perf_counter() - t_node) * 1000, 2)
            logger.warning("chat.node_timeout", node=node_name, route=route,
                           duration_ms=duration_ms, timeout_ms=round(timeout_seconds * 1000, 2))
            observe_chat_error(node=node_name)
            observe_chat_stage(
                stage=node_name,
                route=route,
                status="timeout",
                duration_ms=round(timeout_seconds * 1000, 2),
            )
            return _fallback_update(node_name, state)
        except Exception as exc:
            duration_ms = round((perf_counter() - t_node) * 1000, 2)
            logger.warning("chat.node_failed", node=node_name, route=route,
                           duration_ms=duration_ms, error=str(exc)[:200])
            observe_chat_error(node=node_name)
            observe_chat_stage(
                stage=node_name,
                route=route,
                status="error",
                duration_ms=0.0,
            )
            return _fallback_update(node_name, state)
    return _wrapped


def build_chat_graph() -> Any:
    builder = StateGraph(ChatGraphState)

    query_router_wrapped = _with_node_timeout("query_router", query_router_node)
    retrieval_planner_wrapped = _with_node_timeout("retrieval_planner", retrieval_planner_node)
    retrieval_engine_wrapped = _with_node_timeout("retrieval_engine", retrieval_engine_node)
    web_search_broker_wrapped = _with_node_timeout("web_search_broker", web_search_broker_node)
    answer_generator_wrapped = _with_node_timeout("answer_generator", answer_generator_node)
    citation_verifier_wrapped = _with_node_timeout("citation_verifier", citation_verifier_node)

    async def _parallel_fetch(state: ChatGraphState) -> dict[str, Any]:
        route = state.get("route", "general")
        t0 = perf_counter()
        retrieval_task = asyncio.create_task(retrieval_engine_wrapped(state))
        web_task = asyncio.create_task(web_search_broker_wrapped(state))
        retrieval_result, web_result = await asyncio.gather(
            retrieval_task,
            web_task,
            return_exceptions=True,
        )
        merged: dict[str, Any] = {}
        if isinstance(retrieval_result, Exception):
            logger.warning("chat.parallel_fetch_retrieval_exception", route=route, error=str(retrieval_result)[:200])
            merged.update(_fallback_update("retrieval_engine", state))
        elif isinstance(retrieval_result, dict):
            merged.update(retrieval_result)
        else:
            merged.update(_fallback_update("retrieval_engine", state))

        if isinstance(web_result, Exception):
            logger.warning("chat.parallel_fetch_web_exception", route=route, error=str(web_result)[:200])
            merged.update(_fallback_update("web_search_broker", state))
        elif isinstance(web_result, dict):
            merged.update(web_result)
        else:
            merged.update(_fallback_update("web_search_broker", state))

        logger.info("chat.parallel_fetch_done", route=route, duration_ms=round((perf_counter() - t0) * 1000, 2))
        return merged

    builder.add_node("query_router", query_router_wrapped)
    builder.add_node("retrieval_planner", retrieval_planner_wrapped)
    builder.add_node("parallel_fetch", _with_node_timeout("parallel_fetch", _parallel_fetch))
    builder.add_node("answer_generator", answer_generator_wrapped)
    builder.add_node("citation_verifier", citation_verifier_wrapped)

    builder.add_edge(START, "query_router")
    builder.add_edge("query_router", "retrieval_planner")
    builder.add_edge("retrieval_planner", "parallel_fetch")
    builder.add_edge("parallel_fetch", "answer_generator")
    builder.add_edge("answer_generator", "citation_verifier")
    builder.add_edge("citation_verifier", END)

    return builder.compile()


_graph = None


def get_chat_graph():
    global _graph
    if _graph is None:
        _graph = build_chat_graph()
    return _graph
