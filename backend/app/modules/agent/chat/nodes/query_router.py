"""Node 1: Query Router — 将用户 query 分到 4 类场景。

使用 LangChain with_structured_output 获得类型安全的结构化输出。
"""

from __future__ import annotations

import re
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
    need_web_search: bool = Field(
        default=False,
        description="Whether web search should be used for this query.",
    )
    web_search_reason: str = Field(
        default="not_needed",
        description="Reason for web search decision.",
    )


# ── 快速规则 ──────────────────────────────────────────────────────

_RECOMMEND_HINTS = ("推荐", "相关", "类似", "similar", "recommend", "related")
_NOTEBOOK_HINTS = ("所有文章", "笔记本", "对比", "综述", "总结", "compare", "across")
_WEB_HINTS = (
    "最新", "近期", "最近", "动态", "新闻", "官网", "价格", "版本", "发布", "政策",
    "latest", "recent", "current", "news", "official", "price", "release", "update",
)
_GENERAL_WEB_HINTS = (
    "今天", "现在", "本周", "本月", "热点", "实时",
    "today", "now", "this week", "this month", "breaking",
)

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

    # ========== LLM 结构化输出路由 ==========
    t_model = perf_counter()
    model = build_lite_llm()
    logger.debug("chat.router_build_model", duration_ms=_ms(t_model))
    if model is None:
        return _rule_fallback_result(
            query=query,
            query_lower=query_lower,
            article_id=article_id,
            duration_ms=_ms(t0),
            status="model_unavailable",
        )

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
        t_llm = perf_counter()
        decision: RouteDecision = await structured_model.ainvoke(messages)
        logger.info("chat.router_llm_structured", duration_ms=_ms(t_llm), route=decision.route.value)
        route = decision.route.value
        observe_chat_stage(stage="query_router", route=route, status="ok", duration_ms=_ms(t0))
        tools_needed, web_reason = _decide_tools(
            route=route,
            query=query_lower,
            llm_need=bool(getattr(decision, "need_web_search", False)),
            llm_reason=str(getattr(decision, "web_search_reason", "") or "").strip().lower(),
        )
        return {
            "route": route,
            "retrieval_scope": decision.retrieval_scope,
            "output_mode": decision.output_mode,
            "tools_needed": tools_needed,
            "router_need_web_search": "web_search" in tools_needed,
            "router_web_search_reason": web_reason,
        }
    except Exception as exc:
        logger.warning("chat.router_structured_failed", error=str(exc)[:200], duration_ms=_ms(t0))
        observe_chat_error(node="query_router")
        try:
            fallback_prompt = HumanMessage(
                content=(
                    "只输出一个路由标签，不要解释："
                    "article_qa / notebook_search / recommendation / general。"
                )
            )
            t_llm_text = perf_counter()
            raw = await model.ainvoke([*messages, fallback_prompt])
            route = _extract_route_from_text(_message_text(raw))
            if route:
                tools_needed, web_reason = _decide_tools(route=route, query=query_lower)
                logger.info("chat.router_llm_text_fallback", duration_ms=_ms(t_llm_text), route=route)
                observe_chat_stage(stage="query_router", route=route, status="llm_text", duration_ms=_ms(t0))
                return _build_result(
                    route=route,
                    tools_needed=tools_needed,
                    web_reason=web_reason,
                )
        except Exception as plain_exc:
            logger.warning("chat.router_text_fallback_failed", error=str(plain_exc)[:200])

    return _rule_fallback_result(
        query=query,
        query_lower=query_lower,
        article_id=article_id,
        duration_ms=_ms(t0),
        status="rule_fallback",
    )


def _rule_match(query: str, query_lower: str, article_id: str | None) -> str | None:
    if any(h in query for h in _RECOMMEND_HINTS):
        return "recommendation"
    if any(h in query_lower for h in _NOTEBOOK_HINTS):
        return "notebook_search"
    if article_id:
        # 当前文章上下文存在时，默认优先走 article_qa，避免轻问句被误路由到 general。
        return "article_qa"
    return None


def _rule_fallback_result(
    *,
    query: str,
    query_lower: str,
    article_id: str | None,
    duration_ms: float,
    status: str,
) -> dict[str, Any]:
    t_rule = perf_counter()
    route = _rule_match(query, query_lower, article_id) or ("article_qa" if article_id else "general")
    tools_needed, web_reason = _decide_tools(route=route, query=query_lower)
    logger.debug(
        "chat.router_rule_match",
        route=route,
        duration_ms=_ms(t_rule),
        fallback_status=status,
    )
    observe_chat_stage(stage="query_router", route=route, status=status, duration_ms=duration_ms)
    return _build_result(
        route=route,
        tools_needed=tools_needed,
        web_reason=web_reason,
    )


def _build_result(route: str, *, tools_needed: list[str], web_reason: str) -> dict[str, Any]:
    return {
        "route": route,
        "retrieval_scope": _SCOPE_MAP.get(route, "none"),
        "output_mode": "list" if route == "recommendation" else ("detailed" if route != "general" else "concise"),
        "tools_needed": tools_needed,
        "router_need_web_search": "web_search" in tools_needed,
        "router_web_search_reason": web_reason,
    }


def _decide_tools(
    *,
    route: str,
    query: str,
    llm_need: bool = False,
    llm_reason: str = "",
) -> tuple[list[str], str]:
    tools = list(_TOOLS_MAP.get(route, []))
    need_web = False
    reason = "not_needed"

    if llm_need:
        need_web = True
        reason = _normalize_web_reason(llm_reason)
    elif any(hint in query for hint in _WEB_HINTS):
        need_web = True
        reason = "router_freshness"
    elif route in {"recommendation", "notebook_search"}:
        need_web = True
        reason = "router_route_policy"
    elif route == "general" and any(hint in query for hint in _GENERAL_WEB_HINTS):
        need_web = True
        reason = "router_general_freshness"

    if need_web and "web_search" not in tools:
        tools.append("web_search")
    return tools, reason


def _normalize_web_reason(reason: str) -> str:
    value = (reason or "").strip().lower()
    if not value:
        return "router_llm"
    allowed = {
        "router_llm",
        "router_freshness",
        "router_route_policy",
        "router_general_freshness",
        "external_fact",
        "freshness",
        "not_needed",
    }
    if value in allowed:
        return value
    if any(hint in value for hint in ("fresh", "latest", "recent", "news", "动态", "最新", "近期")):
        return "router_freshness"
    if any(hint in value for hint in ("recommend", "related", "推荐", "相关")):
        return "router_route_policy"
    return "router_llm"


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")[:200]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _extract_route_from_text(text: str) -> str | None:
    lowered = (text or "").strip().lower()
    if not lowered:
        return None
    match = re.search(r"\b(article_qa|notebook_search|recommendation|general)\b", lowered)
    if match:
        return match.group(1)
    alias_map = {
        "article": "article_qa",
        "notebook": "notebook_search",
        "recommend": "recommendation",
    }
    for alias, mapped in alias_map.items():
        if alias in lowered:
            return mapped
    return None


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
