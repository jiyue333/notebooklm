from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.search.dto import SearchCandidateDTO
from app.modules.search.models import SearchResult, SearchSession


async def create_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    normalized_query: str,
    mode: str,
    execution_mode: str,
    provider_name: str,
    provider_request_json: dict,
    status: str,
    mode_label: str,
    created_at: datetime,
    expires_at: datetime,
) -> SearchSession:
    search_session = SearchSession(
        user_id=user_id,
        notebook_id=notebook_id,
        query=query,
        normalized_query=normalized_query,
        mode=mode,
        execution_mode=execution_mode,
        provider_name=provider_name,
        provider_request_json=provider_request_json,
        status=status,
        mode_label=mode_label,
        result_count=0,
        created_at=created_at,
        expires_at=expires_at,
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
        session.add(
            SearchResult(
                search_session_id=search_session_id,
                provider_result_id=candidate.provider_result_id,
                raw_url=candidate.raw_url,
                canonical_url=candidate.canonical_url,
                url_hash=sha256(candidate.canonical_url.encode("utf-8")).hexdigest(),
                title=candidate.title,
                description=candidate.description,
                author=candidate.author,
                published_at=candidate.published_at,
                domain=candidate.domain,
                favicon_url=candidate.favicon_url,
                display_rank=candidate.display_rank,
                preview_markdown=candidate.preview_markdown,
                raw_payload_json=candidate.raw_payload,
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
