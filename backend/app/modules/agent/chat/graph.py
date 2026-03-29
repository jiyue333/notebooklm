"""Chat LangGraph 编排。

flow: query_router → retrieval_planner → [retrieval_engine | skip] → web_search_broker
      → answer_generator → citation_verifier → END
"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Awaitable, Callable
from typing import Any, Literal

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


def _should_retrieve(state: ChatGraphState) -> Literal["retrieve", "skip"]:
    plan: RetrievalPlanSpec = state.get("retrieval_plan", RetrievalPlanSpec())
    if plan.strategy == "skip":
        return "skip"
    return "retrieve"


def _fallback_update(node_name: str, state: ChatGraphState) -> dict[str, Any]:
    route = state.get("route", "general")
    if node_name == "query_router":
        return {
            "route": "article_qa" if state.get("article_id") else "general",
            "retrieval_scope": "article" if state.get("article_id") else "none",
            "output_mode": "concise",
            "tools_needed": [],
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
        try:
            if timeout_seconds <= 0.011:
                raise asyncio.TimeoutError()
            return await asyncio.wait_for(node_fn(state), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            observe_chat_error(node=node_name)
            observe_chat_stage(
                stage=node_name,
                route=route,
                status="timeout",
                duration_ms=round(timeout_seconds * 1000, 2),
            )
            return _fallback_update(node_name, state)
        except Exception as exc:
            logger.warning("chat.node_failed", node=node_name, error=str(exc)[:200])
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

    builder.add_node("query_router", _with_node_timeout("query_router", query_router_node))
    builder.add_node("retrieval_planner", _with_node_timeout("retrieval_planner", retrieval_planner_node))
    builder.add_node("retrieval_engine", _with_node_timeout("retrieval_engine", retrieval_engine_node))
    builder.add_node("web_search_broker", _with_node_timeout("web_search_broker", web_search_broker_node))
    builder.add_node("answer_generator", _with_node_timeout("answer_generator", answer_generator_node))
    builder.add_node("citation_verifier", _with_node_timeout("citation_verifier", citation_verifier_node))

    builder.add_edge(START, "query_router")
    builder.add_edge("query_router", "retrieval_planner")
    builder.add_conditional_edges("retrieval_planner", _should_retrieve, {
        "retrieve": "retrieval_engine",
        "skip": "web_search_broker",
    })
    builder.add_edge("retrieval_engine", "web_search_broker")
    builder.add_edge("web_search_broker", "answer_generator")
    builder.add_edge("answer_generator", "citation_verifier")
    builder.add_edge("citation_verifier", END)

    return builder.compile()


_graph = None


def get_chat_graph():
    global _graph
    if _graph is None:
        _graph = build_chat_graph()
    return _graph
