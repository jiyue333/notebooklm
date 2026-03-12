from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
from typing import Any

from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.sessions.dto import CreateSearchSessionInput, SearchCandidateDTO
from app.modules.search.sessions.models import SearchResult, SearchSession


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
            (_sanitize_text(key) if isinstance(key, str) else key): _sanitize_json(item)
            for key, item in value.items()
        }
    return value


async def create_search_session(
    session: AsyncSession,
    *,
    input: CreateSearchSessionInput,
) -> SearchSession:
    search_session = SearchSession(
        **asdict(input),
        result_count=0,
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


async def get_search_session_by_id(session: AsyncSession, *, search_session_id: str) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession).where(SearchSession.id == search_session_id)
    )
    return result.scalar_one_or_none()


async def list_search_results(session: AsyncSession, *, search_session_id: str) -> list[SearchResult]:
    result = await session.execute(
        select(SearchResult)
        .where(SearchResult.search_session_id == search_session_id)
        .order_by(SearchResult.display_rank.asc(), desc(SearchResult.created_at))
    )
    return list(result.scalars().all())


async def list_search_results_by_ids(
    session: AsyncSession,
    *,
    search_session_id: str,
    result_ids: list[str],
) -> list[SearchResult]:
    if not result_ids:
        return []
    result = await session.execute(
        select(SearchResult)
        .where(
            SearchResult.search_session_id == search_session_id,
            SearchResult.id.in_(result_ids),
        )
        .order_by(SearchResult.display_rank.asc())
    )
    return list(result.scalars().all())


async def replace_search_results(
    session: AsyncSession,
    *,
    search_session_id: str,
    candidates: list[SearchCandidateDTO],
    created_at: datetime,
) -> None:
    await session.execute(delete(SearchResult).where(SearchResult.search_session_id == search_session_id))
    for candidate in candidates:
        canonical_url = _sanitize_text(candidate.canonical_url) or ""
        session.add(
            SearchResult(
                search_session_id=search_session_id,
                provider_result_id=_sanitize_text(candidate.provider_result_id),
                raw_url=_sanitize_text(candidate.raw_url) or "",
                canonical_url=canonical_url,
                url_hash=sha256(canonical_url.encode("utf-8")).hexdigest(),
                title=_sanitize_text(candidate.title) or "Untitled result",
                description=_sanitize_text(candidate.description),
                author=_sanitize_text(candidate.author),
                published_at=candidate.published_at,
                domain=_sanitize_text(candidate.domain),
                favicon_url=_sanitize_text(candidate.favicon_url),
                display_rank=candidate.display_rank,
                preview_markdown=_sanitize_text(candidate.preview_markdown),
                raw_payload_json=_sanitize_json(candidate.raw_payload),
                created_at=created_at,
            )
        )


async def touch_search_session(
    session: AsyncSession,
    *,
    search_session: SearchSession,
    status: str | None = None,
    execution_mode: str | None = None,
    result_count: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    completed_at: datetime | None = None,
) -> SearchSession:
    if status is not None:
        search_session.status = status
    if execution_mode is not None:
        search_session.execution_mode = execution_mode
    if result_count is not None:
        search_session.result_count = result_count
    search_session.error_code = error_code
    search_session.error_message = error_message
    if completed_at is not None:
        search_session.completed_at = completed_at
    await session.flush()
    return search_session


async def expire_stale_search_sessions(session: AsyncSession) -> int:
    result = await session.execute(
        select(SearchSession).where(
            SearchSession.expires_at.is_not(None),
            SearchSession.expires_at < datetime.now(UTC),
            SearchSession.status.in_(["queued", "running"]),
        )
    )
    sessions = list(result.scalars().all())
    for search_session in sessions:
        search_session.status = "expired"
        search_session.completed_at = datetime.now(UTC)
    await session.flush()
    return len(sessions)
