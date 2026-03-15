"""Search session orchestration.

Coordinates the ADR-001 pipeline with persistence, caching, and
async-job fallback for deep mode.
"""

from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.cache import delete_keys, get_json, search_session_key, set_json
from app.infra.db.session import get_session_manager
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.search.pipeline import run_pipeline
from app.modules.search.pipeline.observer import SearchPipelineObserver
from app.modules.search.pipeline.types import NotebookContext, PipelineContext
from app.modules.search.sessions import repo
from app.modules.search.sessions.models import SearchResult, SearchSession
from app.modules.search.sessions.schemas import (
    SearchCardView,
    SearchResponse,
    SearchSessionView,
)

logger = structlog.get_logger(__name__)


# ── public API ─────────────────────────────────────────────────────────────

async def start_search(
    db: AsyncSession,
    *,
    user,
    notebook_id: str,
    query: str,
    mode: str,
    max_results: int,
    freshness_hours: int | None,
    exa_api_key: str,
    notebook_title: str = "",
    existing_article_urls: list[str] | None = None,
    existing_article_titles: list[str] | None = None,
) -> SearchResponse:
    """Create a search session and run it immediately or queue it."""

    execution_mode = "async" if mode == "deep" else "sync"
    provider_request_json = {
        "query": query.strip(),
        "mode": mode,
        "maxResults": max_results,
        "freshnessHours": freshness_hours,
    }

    search_session = await repo.create_search_session(
        db,
        user_id=user.id,
        notebook_id=notebook_id,
        query=query.strip(),
        mode=mode,
        execution_mode=execution_mode,
        provider_request_json=provider_request_json,
        provider_name="hybrid",
    )
    await db.commit()
    await db.refresh(search_session)

    if execution_mode == "async":
        job = await jobs_repo.create_search_deep_job(
            db,
            search_session_id=search_session.id,
            dedupe_key=f"search_deep:{search_session.id}",
            payload_json={"searchSessionId": search_session.id},
            created_at=datetime.now(UTC),
        )
        await db.commit()
        await job_publisher.publish_jobs(db, [job])
        await db.commit()
        return SearchResponse(
            item=SearchSessionView(
                searchSessionId=search_session.id,
                mode=search_session.mode,
                modeLabel=search_session.mode_label,
                status=search_session.status,
                execution=search_session.execution_mode,
            ),
            items=[],
            message="search accepted",
        )

    try:
        response = await _execute(
            search_session,
            exa_api_key=exa_api_key,
            max_results=max_results,
            freshness_hours=freshness_hours,
            notebook_title=notebook_title,
            existing_article_urls=existing_article_urls or [],
            existing_article_titles=existing_article_titles or [],
        )
        return response
    except Exception:
        logger.exception(
            "search.start.failed",
            search_session_id=search_session.id,
        )
        raise


async def execute_search_session(
    *,
    search_session_id: str,
    exa_api_key: str,
) -> SearchResponse:
    """Execute a queued search session by id."""

    async for db in get_session_manager().session():
        search_session = await repo.get_search_session_by_id(
            db,
            search_session_id=search_session_id,
        )
        if search_session is None:
            raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

        notebook = await notebooks_repo.get_notebook(
            db,
            user_id=search_session.user_id,
            notebook_id=search_session.notebook_id,
        )
        if notebook is None:
            raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

        existing_articles = await notebooks_repo.list_articles_by_notebook(
            db,
            user_id=search_session.user_id,
            notebook_id=search_session.notebook_id,
        )
        existing_urls = [a.source_url for a in existing_articles if a.source_url]
        existing_titles = [a.title for a in existing_articles if a.title]
        provider_request = search_session.provider_request_json or {}
        max_results = int(provider_request.get("maxResults") or 10)
        freshness_hours = provider_request.get("freshnessHours")
        if freshness_hours is not None:
            freshness_hours = int(freshness_hours)

        return await _execute(
            search_session,
            exa_api_key=exa_api_key,
            max_results=max_results,
            freshness_hours=freshness_hours,
            notebook_title=notebook.title or "",
            existing_article_urls=existing_urls,
            existing_article_titles=existing_titles,
        )


async def get_search_session(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> SearchResponse:
    """Return a cached or freshly-built search session response."""

    cache_key = search_session_key(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    cached = await get_json(cache_key)
    if isinstance(cached, dict):
        return SearchResponse(**cached)

    search_session = await repo.get_search_session(
        db,
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    # expire if overdue
    if (
        search_session.expires_at
        and search_session.expires_at < datetime.now(UTC)
        and search_session.status not in {"completed", "failed", "expired"}
    ):
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="expired",
            completed_at=datetime.now(UTC),
        )
        await db.commit()

    results: list[SearchResult] = []
    if search_session.status == "completed":
        results = await repo.list_search_results(db, search_session_id=search_session.id)

    response = _build_response(search_session, results)
    await _cache_response(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    return response


# ── core execution ─────────────────────────────────────────────────────────

async def _execute(
    search_session: SearchSession,
    *,
    exa_api_key: str,
    max_results: int,
    freshness_hours: int | None,
    notebook_title: str,
    existing_article_urls: list[str],
    existing_article_titles: list[str],
) -> SearchResponse:
    """Run the pipeline within its own DB session and persist results."""

    async for db in get_session_manager().session():
        started_at = perf_counter()

        ss = await repo.get_search_session_by_id(
            db, search_session_id=search_session.id,
        )
        if ss is None:
            raise AppError(404, "search session not found", code="search_session_not_found")

        await repo.update_session_status(db, search_session=ss, status="running")
        await db.commit()

        try:
            ctx = PipelineContext(
                user_query=ss.query,
                search_mode=ss.mode,
                notebook=NotebookContext(
                    notebook_id=ss.notebook_id,
                    notebook_title=notebook_title,
                    existing_article_urls=existing_article_urls,
                    existing_article_titles=existing_article_titles,
                ),
                exa_api_key=exa_api_key,
                max_results=max_results,
                freshness_hours=freshness_hours,
            )

            observer = SearchPipelineObserver(mode=ss.mode)
            pipeline_result = await run_pipeline(ctx, observer=observer)

            completed_at = datetime.now(UTC)
            await repo.save_search_results(
                db,
                search_session_id=ss.id,
                cards=pipeline_result.cards,
                created_at=completed_at,
            )
            await repo.update_session_status(
                db,
                search_session=ss,
                status="completed",
                result_count=len(pipeline_result.cards),
                completed_at=completed_at,
            )
            await db.commit()

            elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.info(
                "search.execute.completed",
                search_session_id=ss.id,
                card_count=len(pipeline_result.cards),
                elapsed_ms=elapsed_ms,
                stage_timings=pipeline_result.elapsed_stages,
            )

            results = await repo.list_search_results(db, search_session_id=ss.id)
            response = _build_response(
                ss,
                results,
                meta={
                    "provider": ss.provider_name,
                    "elapsedMs": elapsed_ms,
                    "rawCandidateCount": pipeline_result.raw_candidate_count,
                    "canonicalCandidateCount": pipeline_result.canonical_candidate_count,
                    "stageTimings": pipeline_result.elapsed_stages,
                },
            )
            await _cache_response(
                user_id=ss.user_id,
                notebook_id=ss.notebook_id,
                search_session_id=ss.id,
                response=response,
                status=ss.status,
            )
            return response

        except Exception as exc:
            completed_at = datetime.now(UTC)
            error_msg = str(exc)[:500]
            await db.rollback()

            ss = await repo.get_search_session_by_id(db, search_session_id=search_session.id) or ss
            await repo.update_session_status(
                db,
                search_session=ss,
                status="failed",
                error_code="pipeline_failed",
                error_message=error_msg,
                completed_at=completed_at,
            )
            await db.commit()

            logger.exception(
                "search.execute.failed",
                search_session_id=search_session.id,
                error=error_msg,
            )
            raise AppError(502, "搜索执行失败", code="pipeline_failed")

    raise AppError(500, "search execution unavailable", code="search_execution_unavailable")


# ── response builders ──────────────────────────────────────────────────────

def _build_response(
    ss: SearchSession,
    results: list[SearchResult],
    *,
    meta: dict | None = None,
) -> SearchResponse:
    session_view = SearchSessionView(
        searchSessionId=ss.id,
        mode=ss.mode,
        modeLabel=ss.mode_label,
        status=ss.status,
        execution=ss.execution_mode,
    )
    card_views = [_result_to_card_view(r) for r in results]
    return SearchResponse(
        item=session_view,
        items=card_views,
        meta=meta or {"provider": ss.provider_name},
    )


def _result_to_card_view(r: SearchResult) -> SearchCardView:
    payload = r.raw_payload_json or {}
    return SearchCardView(
        id=r.id,
        title=r.title,
        url=r.raw_url,
        sourceName=r.domain or "",
        sourceTypeBadge=payload.get("source_type_badge", ""),
        publishedAt=r.published_at,
        authorityBadge=payload.get("authority_badge"),
        whySelected=payload.get("why_selected", ""),
        highlights=payload.get("highlights", []),
        importSuggestion=payload.get("import_suggestion", "optional"),
        description=r.description,
        author=r.author,
        displayRank=r.display_rank,
    )


# ── caching ────────────────────────────────────────────────────────────────

async def _cache_response(
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
    response: SearchResponse,
    status: str,
) -> None:
    settings = get_settings()
    ttl = (
        settings.cache_ttl_search_session_completed_seconds
        if status in {"completed", "failed", "expired"}
        else settings.cache_ttl_search_session_pending_seconds
    )
    await set_json(
        search_session_key(
            user_id=user_id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
        ),
        response.model_dump(mode="json"),
        ttl_seconds=ttl,
    )


