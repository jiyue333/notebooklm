from __future__ import annotations

from typing import Literal, cast

import structlog
from pydantic import BaseModel, Field

from app.modules.ai.langchain_factory import build_chat_router_prompt, require_user_chat_model

ChatRoute = Literal["CURRENT_ARTICLE", "RELATED_ARTICLES", "EVIDENCE_LOOKUP"]

logger = structlog.get_logger(__name__)


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
        return ChatRouteDecision(
            route="EVIDENCE_LOOKUP",
            reason="当前没有打开文章，已自动降级到当前 notebook 证据检索。",
            confidence=decision.confidence,
        )
    return decision


def _fallback_route(*, message: str, article_id: str | None) -> ChatRouteDecision:
    normalized = message.lower()
    if any(hint in normalized for hint in ("类似", "相关", "还有", "以前看过", "similar", "related", "another")):
        return ChatRouteDecision(
            route="RELATED_ARTICLES",
            reason="fallback: 命中了相关文章关键词。",
            confidence=0.35,
        )
    if any(hint in normalized for hint in ("证据", "出处", "引用", "原文", "依据", "quote", "citation", "evidence")):
        return ChatRouteDecision(
            route="EVIDENCE_LOOKUP",
            reason="fallback: 命中了证据检索关键词。",
            confidence=0.35,
        )
    if article_id:
        return ChatRouteDecision(
            route="CURRENT_ARTICLE",
            reason="fallback: 当前存在打开文章，默认按当前文章处理。",
            confidence=0.2,
        )
    return ChatRouteDecision(
        route="EVIDENCE_LOOKUP",
        reason="fallback: 无当前文章时默认按当前 notebook 证据检索处理。",
        confidence=0.2,
    )
