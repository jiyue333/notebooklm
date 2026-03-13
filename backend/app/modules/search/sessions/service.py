from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.cache import delete_keys, get_json, search_session_key, set_json
from app.infra.db.session import get_session_manager
from app.infra.providers.exa.mapper import ExaResultMapper
from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchMode, ExaSearchRequest
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_search_request
from app.modules.auth.repo import get_user_by_id
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.settings.runtime import resolve_search_api_key
from app.modules.search.sessions import repo as repo_search
from app.modules.search.sessions.dto import CreateSearchSessionInput
from app.modules.search.sessions.error_utils import sanitize_search_error_message
from app.modules.search.sessions.models import SearchSession
from app.modules.search.sessions.quality import score_search_results
from app.modules.search.sessions.view_builder import build_search_response, build_search_session_view
from app.modules.tracker import SearchTracker
from app.modules.tracker.stage_timer import elapsed_ms

logger = structlog.get_logger(__name__)

MODE_LABELS = {
    "fast": "Fast Research",
    "auto": "Auto Research",
    "deep": "Deep Research",
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
    bind_observability_context(user_id=user.id, notebook_id=notebook_id, provider="exa")
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

    create_input = CreateSearchSessionInput(
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
    # 1. create session
    search_session = await repo_search.create_search_session(
        request_session,
        input=create_input,
    )
    await request_session.commit()
    await request_session.refresh(search_session)

    # 2. jobs or sync
    if mode == "deep":
        await _enqueue_search_job(request_session, search_session.id)
        observe_search_request(mode=mode, execution="async", status="accepted")
        response = {
            "item": build_search_session_view(search_session),
            "items": [],
            "message": "search accepted",
        }
        await _cache_search_response(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
            response=response,
            status=search_session.status,
        )
        return response

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
        response = {
            "item": build_search_session_view(search_session),
            "items": [],
            "message": "search accepted",
        }
        await _cache_search_response(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
            response=response,
            status=search_session.status,
        )
        return response


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
        provider_name = search_session.provider_name
        mode_name = search_session.mode
        execution_mode = search_session.execution_mode
        status_for_metrics = search_session.status

        await repo_search.touch_search_session(
            session,
            search_session=search_session,
            status="running",
            error_code=None,
            error_message=None,
        )
        await session.commit()
        await invalidate_search_session_cache(
            user_id=search_session.user_id,
            notebook_id=search_session.notebook_id,
            search_session_id=search_session.id,
        )
        status_for_metrics = "running"

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
            await invalidate_search_session_cache(
                user_id=search_session.user_id,
                notebook_id=search_session.notebook_id,
                search_session_id=search_session.id,
            )
            status_for_metrics = "failed"
            raise AppError(422, "请先在设置里配置 Exa API Key", code="search_api_key_required")

        tracker = SearchTracker(mode=mode_name, execution=execution_mode, provider=provider_name)
        client = ExaSearchClient()
        started_at = perf_counter()
        current_stage = "provider_search"
        current_stage_started = started_at
        try:
            request = ExaSearchRequest(
                query=search_session.query,
                mode=cast(ExaSearchMode, search_session.mode),
                max_results=int(search_session.provider_request_json.get("maxResults", 10)),
                freshness_hours=search_session.provider_request_json.get("freshnessHours"),
            )
            with tracker.stage("provider_search"):
                if timeout_seconds is not None:
                    import asyncio

                    payload = await asyncio.wait_for(
                        client.search(request, api_key=exa_api_key),
                        timeout=timeout_seconds,
                    )
                else:
                    payload = await client.search(request, api_key=exa_api_key)

            current_stage = "result_map"
            current_stage_started = perf_counter()
            with tracker.stage("result_map"):
                candidates = ExaResultMapper.map_search_results(payload)

            completed_at = datetime.now(UTC)
            current_stage = "result_persist"
            current_stage_started = perf_counter()
            with tracker.stage("result_persist", span_attrs={"search.result_count": len(candidates)}):
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

            await invalidate_search_session_cache(
                user_id=search_session.user_id,
                notebook_id=search_session.notebook_id,
                search_session_id=search_session.id,
            )
            status_for_metrics = "completed"
            tracker.report_result_count(len(candidates))
            quality_snapshot = score_search_results(
                candidates,
                freshness_hours=search_session.provider_request_json.get("freshnessHours"),
            )
            tracker.report_quality(quality_snapshot)
            await tracker.capture_review_sample(
                user=user,
                search_session_id=search_session.id,
                notebook_id=search_session.notebook_id,
                query=search_session.query,
                freshness_hours=search_session.provider_request_json.get("freshnessHours"),
                candidates=candidates,
                quality_snapshot=quality_snapshot,
            )
        except TimeoutError:
            await session.rollback()
            search_session = await repo_search.get_search_session_by_id(
                session,
                search_session_id=search_session_id,
            ) or search_session
            tracker.report_stage_manual(current_stage, "timeout", elapsed_ms(current_stage_started))
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="queued",
                execution_mode="async",
                error_code=None,
                error_message=None,
            )
            await session.commit()
            await invalidate_search_session_cache(
                user_id=search_session.user_id,
                notebook_id=search_session.notebook_id,
                search_session_id=search_session.id,
            )
            status_for_metrics = "queued"
            raise
        except Exception as exc:
            completed_at = datetime.now(UTC)
            error_message = sanitize_search_error_message(exc)
            await session.rollback()
            tracker.report_stage_manual(current_stage, "error", elapsed_ms(current_stage_started))
            search_session = await repo_search.get_search_session_by_id(
                session,
                search_session_id=search_session_id,
            ) or search_session
            await repo_search.touch_search_session(
                session,
                search_session=search_session,
                status="failed",
                error_code="provider_search_failed",
                error_message=error_message,
                completed_at=completed_at,
            )
            await session.commit()
            await invalidate_search_session_cache(
                user_id=search_session.user_id,
                notebook_id=search_session.notebook_id,
                search_session_id=search_session.id,
            )
            status_for_metrics = "failed"
            logger.exception(
                "sources.search.execute_failed",
                search_session_id=search_session_id,
                error=error_message,
            )
            raise AppError(502, "来源搜索失败", code="provider_search_failed")
        finally:
            tracker.report_provider(status_for_metrics, elapsed_ms(started_at))
            await client.close()

        with tracker.stage("response_build", span_attrs={"provider": search_session.provider_name}):
            results = await repo_search.list_search_results(session, search_session_id=search_session.id)
            response = build_search_response(
                search_session,
                results,
                meta={
                    "provider": search_session.provider_name,
                    "elapsedMs": elapsed_ms(started_at),
                },
            )
            await _cache_search_response(
                user_id=search_session.user_id,
                notebook_id=search_session.notebook_id,
                search_session_id=search_session.id,
                response=response,
                status=search_session.status,
            )

        return response

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
    cache_key = search_session_key(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    cached = await get_json(cache_key)
    if isinstance(cached, dict):
        return cached

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
        await invalidate_search_session_cache(
            user_id=user_id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
        )

    results = []
    if search_session.status == "completed":
        results = await repo_search.list_search_results(session, search_session_id=search_session.id)

    response = build_search_response(search_session, results)
    await _cache_search_response(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    return response


async def invalidate_search_session_cache(
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> None:
    await delete_keys(
        [
            search_session_key(
                user_id=user_id,
                notebook_id=notebook_id,
                search_session_id=search_session_id,
            )
        ]
    )


async def _cache_search_response(
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
    response: dict,
    status: str,
) -> None:
    settings = get_settings()
    ttl_seconds = (
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
        response,
        ttl_seconds=ttl_seconds,
    )
