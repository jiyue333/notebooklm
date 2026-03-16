"""Stage A – Scope Router.

Classifies the user's question into one of four lanes:
article_grounded, general, recommendation, notebook_research.

First version is rule-based (keyword matching).  A future version
can delegate to a small LLM classifier.
"""

from __future__ import annotations

import re

from app.modules.ai.chat.pipeline.types import ChatInput, ChatRoute, RouteDecision

# ── keyword banks ──────────────────────────────────────────────────────────

_ARTICLE_KEYWORDS = re.compile(
    r"\b(this article|this paper|the author|本文|这篇|作者|这里|上面|"
    r"图\s?\d|表\s?\d|第.{1,2}节|section\s?\d|figure\s?\d|table\s?\d)\b",
    re.IGNORECASE,
)

_RECOMMENDATION_KEYWORDS = re.compile(
    r"\b(similar|related|seen before|类似|相似|在哪看过|相关文章|"
    r"recommend|还有哪些|其他文章)\b",
    re.IGNORECASE,
)

_NOTEBOOK_RESEARCH_KEYWORDS = re.compile(
    r"\b(综合|across articles|in this notebook|this topic|"
    r"overall|这个方向|总结一下|所有文章|compare across|"
    r"synthesize|synthesis|多篇|综述)\b",
    re.IGNORECASE,
)


def route(chat_input: ChatInput) -> RouteDecision:
    """Classify the question and return a ``RouteDecision``."""

    q = chat_input.question.strip()

    # Gibberish / meme / very short non-question → general
    if len(q) <= 12 and not _ARTICLE_KEYWORDS.search(q) and not _RECOMMENDATION_KEYWORDS.search(q) and not _NOTEBOOK_RESEARCH_KEYWORDS.search(q):
        return RouteDecision(
            route=ChatRoute.GENERAL,
            confidence=0.6,
            reason="short input with no keyword signal, treat as general",
        )

    article_score = _match_score(_ARTICLE_KEYWORDS, q)
    recom_score = _match_score(_RECOMMENDATION_KEYWORDS, q)
    research_score = _match_score(_NOTEBOOK_RESEARCH_KEYWORDS, q)

    # Boost article_grounded when an article_id is present and cursor is set
    if chat_input.article_id:
        article_score += 0.2
    if chat_input.reading_cursor and chat_input.reading_cursor.section_id:
        article_score += 0.15
    if chat_input.reading_cursor and chat_input.reading_cursor.page is not None:
        article_score += 0.05
    if chat_input.recent_highlights:
        article_score += 0.1
    if len(q.strip()) <= 24 and chat_input.recent_turns:
        article_score += 0.1
    if chat_input.recent_turns and any(turn.get("role") == "assistant" for turn in chat_input.recent_turns):
        research_score += 0.05

    scores = {
        ChatRoute.ARTICLE_GROUNDED: article_score,
        ChatRoute.RECOMMENDATION: recom_score,
        ChatRoute.NOTEBOOK_RESEARCH: research_score,
        ChatRoute.GENERAL: 0.1,  # baseline
    }

    best_route = max(scores, key=scores.get)  # type: ignore[arg-type]
    best_score = scores[best_route]

    # If best score is very low, classify as ambiguous
    if best_score < 0.15:
        return RouteDecision(
            route=ChatRoute.AMBIGUOUS,
            confidence=0.25,
            reason="no strong signal, route remains ambiguous",
            shadow_route=ChatRoute.ARTICLE_GROUNDED if chat_input.article_id else ChatRoute.GENERAL,
        )

    # Determine shadow route for ambiguous cases
    shadow = None
    sorted_routes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    if len(sorted_routes) >= 2 and sorted_routes[1][1] > 0.15:
        runner_up = sorted_routes[1][0]
        if runner_up != best_route:
            shadow = runner_up

    confidence = min(best_score / max(sum(scores.values()), 0.01), 1.0)
    if len(sorted_routes) >= 2 and abs(sorted_routes[0][1] - sorted_routes[1][1]) < 0.08:
        confidence *= 0.7

    return RouteDecision(
        route=best_route,
        confidence=round(confidence, 3),
        reason=f"keyword match for {best_route.value}",
        shadow_route=shadow,
    )


def _match_score(pattern: re.Pattern, text: str) -> float:
    matches = pattern.findall(text)
    return min(len(matches) * 0.3, 1.0)
