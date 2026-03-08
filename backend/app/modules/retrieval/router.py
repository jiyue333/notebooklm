from __future__ import annotations

from typing import Literal

ChatRoute = Literal["CURRENT_ARTICLE", "RELATED_ARTICLES", "GENERAL_NOTEBOOK"]

RELATED_HINTS = (
    "类似",
    "相关",
    "还有",
    "以前看过",
    "还看过",
    "similar",
    "related",
    "else",
    "another",
    "other article",
)


def route_chat_message(message: str, article_id: str | None) -> ChatRoute:
    normalized = message.lower()
    if any(hint in normalized for hint in RELATED_HINTS):
        return "RELATED_ARTICLES"
    if article_id:
        return "CURRENT_ARTICLE"
    return "GENERAL_NOTEBOOK"
