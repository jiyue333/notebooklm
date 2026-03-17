"""AI search service – orchestrates the agent search pipeline.

Integrates with:
  - chat_models (user-configured model) for intent recognition & agent planning
  - lite_models (system model) for scoring & ranking
  - search sessions for persistence & caching
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.chat_models import build_user_chat_model
from app.infra.ai.lite_models import build_lite_llm
from app.modules.agent.search.graph import run_search_agent
from app.modules.search.sessions import repo as search_repo
from app.modules.search.sessions.models import SearchSession
from app.modules.search.sessions.schemas import (
    SearchCardView,
    SearchResponse,
    SearchSessionView,
)

logger = structlog.get_logger(__name__)


async def start_agent_search(
    db: AsyncSession,
    *,
    user,
    notebook_id: str,
    query: str,
    mode: str = "agent",
    max_results: int = 15,
    exa_api_key: str,
    notebook_title: str = "",
    existing_article_urls: list[str] | None = None,
    existing_article_titles: list[str] | None = None,
) -> SearchResponse:
    """Run an AI-agent-powered search and persist results.

    This replaces the rule-based pipeline for users who have
    a chat model configured.
    """
    t0 = perf_counter()

    chat_model = build_user_chat_model(user)
    lite_model = build_lite_llm()

    if chat_model is None:
        from app.api.errors import AppError
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")

    search_session = await search_repo.create_search_session(
        db,
        user_id=user.id,
        notebook_id=notebook_id,
        query=query.strip(),
        mode=mode,
        execution_mode="sync",
        provider_request_json={
            "query": query.strip(),
            "mode": mode,
            "maxResults": max_results,
        },
        provider_name="agent",
    )
    await db.commit()
    await db.refresh(search_session)

    await search_repo.update_session_status(db, search_session=search_session, status="running")
    await db.commit()

    try:
        result = await run_search_agent(
            chat_model,
            lite_model,
            query=query.strip(),
            exa_api_key=exa_api_key,
            notebook_title=notebook_title,
            existing_article_titles=existing_article_titles,
            existing_article_urls=existing_article_urls,
            max_results=max_results,
        )

        elapsed_ms = round((perf_counter() - t0) * 1000, 2)
        cards_data = result.get("cards", [])
        completed_at = datetime.now(UTC)

        result_ids = await _persist_results(
            db, search_session=search_session, cards=cards_data,
        )
        await search_repo.update_session_status(
            db,
            search_session=search_session,
            status="completed",
            result_count=len(cards_data),
            completed_at=completed_at,
        )
        await db.commit()

        logger.info(
            "ai_search.completed",
            search_session_id=search_session.id,
            card_count=len(cards_data),
            raw_count=result.get("raw_count", 0),
            elapsed_ms=elapsed_ms,
        )

        for card, rid in zip(cards_data, result_ids):
            card["_id"] = rid

        return _build_response(search_session, cards_data, elapsed_ms=elapsed_ms, meta={
            "provider": "agent",
            "elapsedMs": elapsed_ms,
            "rawCount": result.get("raw_count", 0),
            "scoredCount": result.get("scored_count", 0),
            "intent": result.get("intent", {}),
        })

    except Exception as exc:
        error_msg = str(exc)[:500]
        await db.rollback()

        ss = await search_repo.get_search_session_by_id(
            db, search_session_id=search_session.id,
        ) or search_session
        await search_repo.update_session_status(
            db,
            search_session=ss,
            status="failed",
            error_code="agent_search_failed",
            error_message=error_msg,
            completed_at=datetime.now(UTC),
        )
        await db.commit()

        logger.exception(
            "ai_search.failed",
            search_session_id=search_session.id,
            error=error_msg,
        )
        from app.api.errors import AppError
        raise AppError(502, "智能搜索执行失败", code="agent_search_failed")


# ── Persistence ─────────────────────────────────────────────────────────────


async def _persist_results(
    db: AsyncSession,
    *,
    search_session: SearchSession,
    cards: list[dict],
) -> list[str]:
    """Save agent search results using the existing search_results table.

    Returns list of created SearchResult IDs.
    """
    from hashlib import sha256
    from app.modules.search.sessions.models import SearchResult

    now = datetime.now(UTC)
    ids: list[str] = []
    for card in cards:
        url = card.get("url", "")
        url_hash = sha256(url.encode()).hexdigest() if url else ""
        sr = SearchResult(
            search_session_id=search_session.id,
            provider_result_id=None,
            raw_url=url,
            canonical_url=url,
            url_hash=url_hash,
            title=card.get("title", "") or "Untitled",
            description=card.get("description"),
            author=card.get("author"),
            published_at=None,
            domain=card.get("source_name", ""),
            display_rank=card.get("display_rank", 0),
            raw_payload_json={
                "source_type_badge": card.get("source_type_badge", ""),
                "authority_badge": card.get("authority_badge"),
                "why_selected": card.get("why_selected", ""),
                "highlights": card.get("highlights", []),
                "import_suggestion": card.get("import_suggestion", "optional"),
                "final_score": card.get("final_score", 0),
            },
            created_at=now,
        )
        db.add(sr)
        await db.flush()
        ids.append(sr.id)
    return ids


# ── Response Building ───────────────────────────────────────────────────────


def _build_response(
    ss: SearchSession,
    cards: list[dict],
    *,
    elapsed_ms: float = 0,
    meta: dict | None = None,
) -> SearchResponse:
    session_view = SearchSessionView(
        searchSessionId=ss.id,
        mode=ss.mode,
        modeLabel=ss.mode_label,
        status=ss.status,
        execution=ss.execution_mode,
    )
    card_views = [_card_to_view(c) for c in cards]
    return SearchResponse(
        item=session_view,
        items=card_views,
        meta=meta or {"provider": "agent", "elapsedMs": elapsed_ms},
    )


def _card_to_view(card: dict) -> SearchCardView:
    return SearchCardView(
        id=card.get("_id", ""),
        title=card.get("title", ""),
        url=card.get("url", ""),
        sourceName=card.get("source_name", ""),
        sourceTypeBadge=card.get("source_type_badge", ""),
        publishedAt=None,
        authorityBadge=card.get("authority_badge"),
        whySelected=card.get("why_selected", ""),
        highlights=card.get("highlights", []),
        importSuggestion=card.get("import_suggestion", "optional"),
        description=card.get("description", ""),
        author=card.get("author"),
        displayRank=card.get("display_rank", 0),
    )
