"""Repository layer for SearchSession / SearchResult persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.pipeline.types import SearchCard
from app.modules.search.sessions.models import SearchResult, SearchSession


# ── sanitisation helpers ───────────────────────────────────────────────────

def _sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\x00", "")


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {
            (_sanitize_text(k) if isinstance(k, str) else k): _sanitize_json(v)
            for k, v in value.items()
        }
    return value


# ── SearchSession CRUD ─────────────────────────────────────────────────────

async def create_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    mode: str,
    execution_mode: str,
    provider_request_json: dict,
    provider_name: str = "hybrid",
    now: datetime | None = None,
) -> SearchSession:
    ts = now or datetime.now(UTC)
    mode_labels = {"fast": "Fast Research", "auto": "Auto Research", "deep": "Deep Research"}
    search_session = SearchSession(
        user_id=user_id,
        notebook_id=notebook_id,
        query=query,
        normalized_query=query.strip().lower(),
        mode=mode,
        execution_mode=execution_mode,
        provider_name=provider_name,
        provider_request_json=provider_request_json,
        status="running" if execution_mode == "sync" else "queued",
        mode_label=mode_labels.get(mode, "Research"),
        result_count=0,
        created_at=ts,
        expires_at=ts.replace(day=ts.day + 1) if ts.day < 28 else ts,
    )
    session.add(search_session)
    await session.flush()
    return search_session


async def get_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession).where(
            SearchSession.id == search_session_id,
            SearchSession.user_id == user_id,
            SearchSession.notebook_id == notebook_id,
        )
    )
    return result.scalar_one_or_none()


async def get_search_session_by_id(
    session: AsyncSession,
    *,
    search_session_id: str,
) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession).where(SearchSession.id == search_session_id)
    )
    return result.scalar_one_or_none()


async def update_session_status(
    session: AsyncSession,
    *,
    search_session: SearchSession,
    status: str,
    result_count: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    completed_at: datetime | None = None,
) -> SearchSession:
    search_session.status = status
    if result_count is not None:
        search_session.result_count = result_count
    search_session.error_code = error_code
    search_session.error_message = error_message
    if completed_at is not None:
        search_session.completed_at = completed_at
    await session.flush()
    return search_session



# ── SearchResult CRUD ──────────────────────────────────────────────────────

async def save_search_results(
    session: AsyncSession,
    *,
    search_session_id: str,
    cards: list[SearchCard],
    created_at: datetime | None = None,
) -> None:
    """Persist pipeline SearchCards as SearchResult rows."""

    ts = created_at or datetime.now(UTC)
    await session.execute(
        delete(SearchResult).where(SearchResult.search_session_id == search_session_id)
    )
    for card in cards:
        session.add(
            SearchResult(
                search_session_id=search_session_id,
                provider_result_id=_sanitize_text(card.provider_result_id),
                raw_url=_sanitize_text(card.url) or "",
                canonical_url=_sanitize_text(card.canonical_url) or "",
                url_hash=card.url_hash or sha256((card.canonical_url or "").encode()).hexdigest(),
                title=_sanitize_text(card.title) or "Untitled",
                description=_sanitize_text(card.description),
                author=_sanitize_text(card.author),
                published_at=card.published_at,
                domain=_sanitize_text(card.domain),
                favicon_url=_sanitize_text(card.favicon_url),
                display_rank=card.display_rank,
                preview_markdown=_sanitize_text(card.preview_markdown),
                raw_payload_json=_sanitize_json({
                    "why_selected": card.why_selected,
                    "source_type_badge": card.source_type_badge,
                    "authority_badge": card.authority_badge,
                    "import_suggestion": card.import_suggestion.value,
                    "highlights": card.highlights,
                    "final_score": card.final_score,
                    "doc_type": card.doc_type.value,
                }),
                created_at=ts,
            )
        )


async def list_search_results(
    session: AsyncSession,
    *,
    search_session_id: str,
) -> list[SearchResult]:
    result = await session.execute(
        select(SearchResult)
        .where(SearchResult.search_session_id == search_session_id)
        .order_by(SearchResult.display_rank.asc(), desc(SearchResult.created_at))
    )
    return list(result.scalars().all())
