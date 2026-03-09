from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.providers.exa.mapper import ExaResultMapper
from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchMode, ExaSearchRequest
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_search_provider, observe_search_request
from app.modules.auth.repo import get_user_by_id
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.settings.runtime import resolve_search_api_key
from app.modules.search import repo_search
from app.modules.search.models import SearchResult, SearchSession

logger = structlog.get_logger(__name__)

MODE_LABELS = {
    "fast": "Fast Research",
    "auto": "Auto Research",
    "deep": "Deep Research",
}


def _build_search_result_view(result: SearchResult) -> dict:
    return {
        "id": result.id,
        "title": result.title,
        "description": result.description or result.preview_markdown or "",
        "icon": "🌐",
        "url": result.raw_url,
        "selected": True,
    }


def _build_session_view(search_session: SearchSession) -> dict:
    return {
        "searchSessionId": search_session.id,
        "mode": search_session.mode,
        "modeLabel": search_session.mode_label,
        "status": search_session.status,
        "execution": search_session.execution_mode,
    }


def _build_response(search_session: SearchSession, results: list[SearchResult], *, meta: dict | None = None) -> dict:
    return {
        "item": _build_session_view(search_session),
        "items": [_build_search_result_view(result) for result in results],
        "meta": meta or {"provider": search_session.provider_name},
    }


async def start_search(
    request_session: AsyncSession,
    *,
    user,
    notebook_id: str,
    query: str,
    mode: str,
    max_results: int,
    freshness_hours: int | None,
) -> dict:
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        provider="exa",
    )
    notebook = await notebooks_repo.get_notebook(
        request_session,
        user_id=user.id,
        notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")
    exa_api_key, _key_source = resolve_search_api_key(user)
    if not exa_api_key:
        raise AppError(422, "请先在设置里配置 Exa API Key", code="search_api_key_required")

    normalized_query = query.strip()
    now = datetime.now(UTC)
    provider_request_json = {
        "query": normalized_query,
        "mode": mode,
        "maxResults": max_results,
        "freshnessHours": freshness_hours,
    }
    execution_mode = "async" if mode == "deep" else "sync"
    status = "queued" if mode == "deep" else "running"

    search_session = await repo_search.create_search_session(
        request_session,
        user_id=user.id,
        notebook_id=notebook_id,
        query=normalized_query,
        normalized_query=normalized_query.lower(),
        mode=mode,
        execution_mode=execution_mode,
        provider_name="exa",
        provider_request_json=provider_request_json,
        status=status,
        mode_label=MODE_LABELS[mode],
        created_at=now,
        expires_at=now + timedelta(days=1),
    )
    await request_session.commit()
    await request_session.refresh(search_session)

    if mode == "deep":
        await _enqueue_search_job(request_session, search_session.id)
        observe_search_request(mode=mode, execution="async", status="accepted")
        return {
            "item": _build_session_view(search_session),
            "items": [],
            "message": "search accepted",
        }

    deadline_seconds = get_settings().search_inline_deadline_ms / 1000
    try:
        response = await execute_search(search_session.id, timeout_seconds=deadline_seconds)
        observe_search_request(mode=mode, execution="sync", status="completed")
        return response
    except TimeoutError:
        request_session.expire_all()
        reloaded = await repo_search.get_search_session(
            request_session,
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
        )
        if reloaded is not None:
            await repo_search.touch_search_session(
                request_session,
                search_session=reloaded,
                status="queued",
                execution_mode="async",
            )
            await request_session.commit()
            search_session = reloaded
        await _enqueue_search_job(request_session, search_session.id)
        observe_search_request(mode=mode, execution="async_fallback", status="accepted")
        return {
            "item": _build_session_view(search_session),
            "items": [],
            "message": "search accepted",
        }


async def execute_search(search_session_id: str, *, timeout_seconds: float | None = None) -> dict:
    async for session in get_session_manager().session():
        search_session = await repo_search.get_search_session_by_id(
            session,
            search_session_id=search_session_id,
        )
        if search_session is None:
            raise AppError(404, "search session not found", code="search_session_not_found")
        bind_observability_context(
            user_id=search_session.user_id,
            notebook_id=search_session.notebook_id,
            search_session_id=search_session.id,
            provider=search_session.provider_name,
        )

        await repo_search.touch_search_session(
            session,
            search_session=search_session,
            status="running",
            error_code=None,
            error_message=None,
        )
        await session.commit()

        user = await get_user_by_id(session, search_session.user_id)
        exa_api_key = None
        if user is not None:
            exa_api_key, _key_source = resolve_search_api_key(user)
        if user is None or not exa_api_key:
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="failed",
                error_code="search_api_key_required",
                error_message="missing user exa api key",
                completed_at=datetime.now(UTC),
            )
            await session.commit()
            raise AppError(422, "请先在设置里配置 Exa API Key", code="search_api_key_required")

        client = ExaSearchClient()
        started_at = perf_counter()
        try:
            request = ExaSearchRequest(
                query=search_session.query,
                mode=cast(ExaSearchMode, search_session.mode),
                max_results=int(search_session.provider_request_json.get("maxResults", 10)),
                freshness_hours=search_session.provider_request_json.get("freshnessHours"),
            )
            if timeout_seconds is not None:
                import asyncio

                payload = await asyncio.wait_for(
                    client.search(request, api_key=exa_api_key),
                    timeout=timeout_seconds,
                )
            else:
                payload = await client.search(request, api_key=exa_api_key)
            candidates = ExaResultMapper.map_search_results(payload)
            completed_at = datetime.now(UTC)
            await repo_search.replace_search_results(
                session,
                search_session_id=search_session.id,
                candidates=candidates,
                created_at=completed_at,
            )
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="completed",
                result_count=len(candidates),
                completed_at=completed_at,
                error_code=None,
                error_message=None,
            )
            await session.commit()
        except TimeoutError:
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="queued",
                execution_mode="async",
                error_code=None,
                error_message=None,
            )
            await session.commit()
            raise
        except Exception as exc:
            completed_at = datetime.now(UTC)
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="failed",
                error_code="provider_search_failed",
                error_message=str(exc),
                completed_at=completed_at,
            )
            await session.commit()
            logger.exception(
                "sources.search.execute_failed",
                search_session_id=search_session.id,
                error=str(exc),
            )
            raise AppError(502, "来源搜索失败", code="provider_search_failed")
        finally:
            observe_search_provider(
                provider=search_session.provider_name,
                mode=search_session.mode,
                status=search_session.status,
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            await client.close()

        results = await repo_search.list_search_results(session, search_session_id=search_session.id)
        return _build_response(
            search_session,
            results,
            meta={
                "provider": search_session.provider_name,
                "elapsedMs": round((perf_counter() - started_at) * 1000, 2),
            },
        )

    raise AppError(500, "search execution unavailable", code="search_execution_unavailable")


async def _enqueue_search_job(session: AsyncSession, search_session_id: str) -> None:
    now = datetime.now(UTC)
    job = await jobs_repo.create_search_deep_job(
        session,
        search_session_id=search_session_id,
        dedupe_key=f"search_deep:{search_session_id}",
        payload_json={"searchSessionId": search_session_id},
        created_at=now,
    )
    await session.commit()
    try:
        await job_publisher.publish_jobs(session, [job])
        await session.commit()
    except Exception as exc:
        logger.exception(
            "sources.search.enqueue_failed",
            search_session_id=search_session_id,
            error=str(exc),
        )
        await session.rollback()


async def get_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> dict:
    search_session = await repo_search.get_search_session(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    if search_session.expires_at and search_session.expires_at < datetime.now(UTC) and search_session.status not in {
        "completed",
        "failed",
        "expired",
    }:
        await repo_search.touch_search_session(
            session,
            search_session=search_session,
            status="expired",
            completed_at=datetime.now(UTC),
        )
        await session.commit()

    results = []
    if search_session.status == "completed":
        results = await repo_search.list_search_results(session, search_session_id=search_session.id)

    return _build_response(search_session, results)
