from __future__ import annotations

from typing import Literal, cast

import structlog
from pydantic import BaseModel, Field

from app.modules.ai.langchain_factory import build_chat_router_prompt, require_user_chat_model

ChatRoute = Literal["CURRENT_ARTICLE", "RELATED_ARTICLES", "EVIDENCE_LOOKUP", "GENERAL"]

logger = structlog.get_logger(__name__)
RELATED_ROUTE_HINTS = ("类似", "相关", "还有", "以前看过", "similar", "related", "another")
EVIDENCE_ROUTE_HINTS = ("证据", "出处", "引用", "原文", "依据", "quote", "citation", "evidence")
GENERAL_ROUTE_HINTS = ("你是谁", "你能做什么", "怎么用", "如何使用", "hello", "hi", "hey", "你好")


class ChatRouteDecision(BaseModel):
    route: ChatRoute
    reason: str = Field(min_length=1, max_length=240)
    confidence: float = Field(ge=0.0, le=1.0)


async def route_chat_message(
    *,
    user,
    notebook_title: str,
    article_id: str | None,
    message: str,
) -> ChatRouteDecision:
    heuristic_decision = _heuristic_route(message=message, article_id=article_id)
    if heuristic_decision is not None:
        return heuristic_decision

    prompt = build_chat_router_prompt()
    model = require_user_chat_model(user)
    router = model.with_structured_output(ChatRouteDecision)
    try:
        decision = cast(
            ChatRouteDecision,
            await (prompt | router).ainvoke(
                {
                    "notebook_title": notebook_title,
                    "has_current_article": "是" if article_id else "否",
                    "user_message": message,
                },
                config={"run_name": "chat_route"},
            ),
        )
    except Exception as exc:
        logger.exception("chat.route_failed", error=str(exc))
        return _fallback_route(message=message, article_id=article_id)

    if decision.route == "CURRENT_ARTICLE" and not article_id:
        fallback_decision = _fallback_route(message=message, article_id=article_id)
        return ChatRouteDecision(
            route=fallback_decision.route,
            reason=f"当前没有打开文章，已自动降级。{fallback_decision.reason}",
            confidence=decision.confidence,
        )
    return decision


def _fallback_route(*, message: str, article_id: str | None) -> ChatRouteDecision:
    heuristic_decision = _heuristic_route(message=message, article_id=article_id)
    if heuristic_decision is not None:
        return heuristic_decision

    if article_id:
        return ChatRouteDecision(
            route="CURRENT_ARTICLE",
            reason="fallback: 当前存在打开文章，默认按当前文章处理。",
            confidence=0.2,
        )
    return ChatRouteDecision(
        route="GENERAL",
        reason="fallback: 无当前文章时默认按通用问题处理。",
        confidence=0.2,
    )


def _heuristic_route(*, message: str, article_id: str | None) -> ChatRouteDecision | None:
    normalized = message.lower()
    if any(hint in normalized for hint in RELATED_ROUTE_HINTS):
        return ChatRouteDecision(
            route="RELATED_ARTICLES",
            reason="heuristic: 命中了相关文章关键词。",
            confidence=0.65,
        )
    if any(hint in normalized for hint in EVIDENCE_ROUTE_HINTS):
        return ChatRouteDecision(
            route="EVIDENCE_LOOKUP",
            reason="heuristic: 命中了证据检索关键词。",
            confidence=0.65,
        )
    if any(hint in normalized for hint in GENERAL_ROUTE_HINTS):
        return ChatRouteDecision(
            route="GENERAL",
            reason="heuristic: 命中了通用问题关键词。",
            confidence=0.65,
        )
    return None
