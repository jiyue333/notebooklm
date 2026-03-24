"""Node 1: Query Router — 将用户 query 分到 4 类场景。

使用 LangChain with_structured_output 获得类型安全的结构化输出。
"""

from __future__ import annotations

from enum import Enum
from time import perf_counter
from typing import Any, Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.infra.ai.lite_models import build_lite_llm
from app.infra.telemetry.metrics import observe_chat_error, observe_chat_stage
from app.modules.agent.chat.prompts import ROUTER_SYSTEM, ROUTER_USER
from app.modules.agent.chat.state import ChatGraphState

logger = structlog.get_logger(__name__)


# ── Structured output schema ──────────────────────────────────────

class RouteEnum(str, Enum):
    article_qa = "article_qa"
    notebook_search = "notebook_search"
    recommendation = "recommendation"
    general = "general"


class RouteDecision(BaseModel):
    """Query routing decision."""

    route: RouteEnum = Field(
        description="The classified query route.",
    )
    retrieval_scope: Literal["article", "notebook", "none"] = Field(
        description="Which scope to search: 'article' for current article, 'notebook' for all articles, 'none' for no local search.",
    )
    output_mode: Literal["concise", "detailed", "list"] = Field(
        default="concise",
        description="Preferred output format.",
    )


# ── 快速规则 ──────────────────────────────────────────────────────

_ARTICLE_HINTS = ("这篇", "本文", "文中", "文章里", "当前文章", "this article", "this paper")
_RECOMMEND_HINTS = ("推荐", "相关", "类似", "similar", "recommend", "related")
_NOTEBOOK_HINTS = ("所有文章", "笔记本", "对比", "综述", "总结", "compare", "across")

_SCOPE_MAP = {
    "article_qa": "article",
    "notebook_search": "notebook",
    "recommendation": "notebook",
    "general": "none",
}
_TOOLS_MAP = {
    "article_qa": ["local_retrieval"],
    "notebook_search": ["local_retrieval"],
    "recommendation": ["local_retrieval"],
    "general": [],
}


async def query_router_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    query = state["query"]
    article_id = state.get("article_id")
    query_lower = query.lower()

    # ========== 快速规则路由 ==========
    rule_route = _rule_match(query, query_lower, article_id)
    if rule_route:
        observe_chat_stage(stage="query_router", route=rule_route, status="rule", duration_ms=_ms(t0))
        return _build_result(rule_route)

    # ========== LLM 结构化输出路由 ==========
    model = build_lite_llm()
    if model is None:
        route = "article_qa" if article_id else "general"
        observe_chat_stage(stage="query_router", route=route, status="fallback", duration_ms=_ms(t0))
        return _build_result(route)

    messages = [
        SystemMessage(content=ROUTER_SYSTEM),
        HumanMessage(content=ROUTER_USER.format(
            notebook_title=state.get("notebook_title", ""),
            article_title=state.get("article_title", "None"),
            has_article="yes" if article_id else "no",
            history_text=_format_history(state.get("history", [])) or "(none)",
            query=query,
        )),
    ]

    try:
        structured_model = model.with_structured_output(RouteDecision)
        decision: RouteDecision = await structured_model.ainvoke(messages)
        route = decision.route.value
        observe_chat_stage(stage="query_router", route=route, status="ok", duration_ms=_ms(t0))
        return {
            "route": route,
            "retrieval_scope": decision.retrieval_scope,
            "output_mode": decision.output_mode,
            "tools_needed": _TOOLS_MAP.get(route, []),
        }
    except Exception as exc:
        logger.warning("chat.router_structured_failed", error=str(exc)[:200])
        observe_chat_error(node="query_router")

    # fallback
    route = "article_qa" if article_id else "general"
    observe_chat_stage(stage="query_router", route=route, status="fallback", duration_ms=_ms(t0))
    return _build_result(route)


def _rule_match(query: str, query_lower: str, article_id: str | None) -> str | None:
    if article_id and any(h in query for h in _ARTICLE_HINTS):
        return "article_qa"
    if any(h in query for h in _RECOMMEND_HINTS):
        return "recommendation"
    if any(h in query_lower for h in _NOTEBOOK_HINTS):
        return "notebook_search"
    return None


def _build_result(route: str) -> dict[str, Any]:
    return {
        "route": route,
        "retrieval_scope": _SCOPE_MAP.get(route, "none"),
        "output_mode": "list" if route == "recommendation" else ("detailed" if route != "general" else "concise"),
        "tools_needed": _TOOLS_MAP.get(route, []),
    }


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")[:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
