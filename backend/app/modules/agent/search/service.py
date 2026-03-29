"""搜索服务：加载上下文、执行搜索图、持久化与缓存。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.ai.lite_models import build_lite_llm
from app.infra.cache import get_json, search_session_key, set_json
from app.infra.db.session import get_session_manager
from app.infra.telemetry.metrics import (
    observe_search_e2e,
    observe_search_empty_slate,
    observe_search_slate_card_count,
)
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search import repo
from app.modules.agent.search.graph import run_search_agent
from app.modules.agent.search.models import SearchResult, SearchSession
from app.modules.agent.search.schemas import SearchResponse
from app.modules.agent.search.state import SearchResponsePayload, SearchResultCardView, SearchRunView

logger = structlog.get_logger(__name__)
_SEARCH_SESSION_ZOMBIE_TIMEOUT_SECONDS_BY_MODE = {
    "fast": 600,
    "auto": 900,
    "deep": 1200,
}
_SEARCH_RUN_TIMEOUT_SECONDS_BY_MODE = {
    "fast": 180,
    "auto": 300,
    "deep": 480,
}
_SEARCH_ACTIVE_SESSION_LIMIT = 3
_SENSITIVE_ERROR_PATTERN = re.compile(r"(sk-[A-Za-z0-9]{16,}|api[_-]?key[=:][^\\s,;]+|token[=:][^\\s,;]+)", re.IGNORECASE)


def _normalize_preferred_sites(preferred_sites: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for site in preferred_sites or []:
        value = str(site or "").strip().lower()
        if not value:
            continue
        normalized.append(value)
    return list(dict.fromkeys(normalized))


def _build_query_signature(
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    mode: str,
    max_results: int,
    preferred_sites: list[str] | None,
) -> str:
    payload = {
        "userId": user_id,
        "notebookId": notebook_id,
        "query": query.strip().lower(),
        "mode": mode,
        "maxResults": int(max_results),
        "preferredSites": sorted(_normalize_preferred_sites(preferred_sites)),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _sanitize_error_message(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return "搜索执行失败"
    return _SENSITIVE_ERROR_PATTERN.sub("[REDACTED]", text)[:500]


async def _mark_session_failed(
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
    error_code: str,
    error_message: str,
) -> None:
    safe_message = _sanitize_error_message(error_message)
    async for session in get_session_manager().session():
        search_session = await repo.get_search_session_by_id(
            session,
            search_session_id=search_session_id,
        )
        if search_session is None:
            return
        await repo.update_session_status(
            session,
            search_session=search_session,
            status="failed",
            error_code=error_code,
            error_message=safe_message,
            completed_at=datetime.now(UTC),
        )
        await session.commit()
        response = _build_response_from_results(search_session, [])
        try:
            await _cache_response(
                user_id=user_id,
                notebook_id=notebook_id,
                search_session_id=search_session.id,
                response=response,
                status=search_session.status,
            )
        except Exception:
            logger.warning(
                "search.cache_write_failed",
                search_session_id=search_session.id,
                status=search_session.status,
            )
        return


async def start_agent_search(
    db: AsyncSession,
    *,
    user,
    notebook_id: str,
    query: str,
    mode: str = "auto",
    max_results: int = 10,
    exa_api_key: str | None,
    tavily_api_key: str | None,
    notebook_title: str = "",
    existing_article_urls: list[str] | None = None,
    notebook_article_summaries: list[dict[str, str]] | None = None,
    preferred_sites: list[str] | None = None,
) -> SearchResponse:
    """执行搜索图，并保存搜索会话与结果。"""
    if not exa_api_key and not tavily_api_key:
        raise AppError(422, "请先配置至少一个搜索引擎 Key", code="search_provider_key_required")

    active_sessions = await repo.count_active_sessions(
        db,
        user_id=user.id,
        notebook_id=notebook_id,
    )
    if active_sessions >= _SEARCH_ACTIVE_SESSION_LIMIT:
        raise AppError(
            429,
            "当前搜索任务过多，请等待现有任务完成后再试",
            code="search_too_many_active_sessions",
        )

    normalized_query = query.strip().lower()
    query_signature = _build_query_signature(
        user_id=user.id,
        notebook_id=notebook_id,
        query=query,
        mode=mode,
        max_results=max_results,
        preferred_sites=preferred_sites,
    )
    reusable_session = await repo.find_reusable_search_session(
        db,
        user_id=user.id,
        notebook_id=notebook_id,
        query_signature=query_signature,
    )
    if reusable_session is not None:
        existing_results: list[SearchResult] = []
        if reusable_session.status in {"completed", "partial", "running", "queued"}:
            existing_results = await repo.list_search_results(
                db,
                search_session_id=reusable_session.id,
            )
        reusable_response = _build_response_from_results(reusable_session, existing_results)
        await _cache_response(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=reusable_session.id,
            response=reusable_response,
            status=reusable_session.status,
        )
        return SearchResponse(**reusable_response.model_dump())

    search_session = await repo.create_search_session(
        db,
        user_id=user.id,
        notebook_id=notebook_id,
        query=query.strip(),
        mode=mode,
        execution_mode="queued",
        provider_request_json={
            "query": normalized_query,
            "mode": mode,
            "maxResults": max_results,
            "preferredSites": preferred_sites or [],
            "querySignature": query_signature,
        },
        provider_name="langgraph_search",
    )
    await db.commit()
    await db.refresh(search_session)

    response = _build_response_from_results(search_session, [])
    await _cache_response(
        user_id=user.id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    asyncio.create_task(
        _run_search_session_async(
            search_session_id=search_session.id,
            user=user,
            notebook_id=notebook_id,
            query=query,
            mode=mode,
            max_results=max_results,
            exa_api_key=exa_api_key,
            tavily_api_key=tavily_api_key,
            notebook_title=notebook_title,
            existing_article_urls=existing_article_urls,
            notebook_article_summaries=notebook_article_summaries,
            preferred_sites=preferred_sites,
        )
    )
    return SearchResponse(**response.model_dump())


async def _run_search_session_async(
    *,
    search_session_id: str,
    user,
    notebook_id: str,
    query: str,
    mode: str,
    max_results: int,
    exa_api_key: str | None,
    tavily_api_key: str | None,
    notebook_title: str,
    existing_article_urls: list[str] | None,
    notebook_article_summaries: list[dict[str, str]] | None,
    preferred_sites: list[str] | None,
) -> None:
    chat_model = build_user_chat_model(user)
    lite_model = build_lite_llm()

    try:
        async for session in get_session_manager().session():
            search_session = await repo.get_search_session_by_id(
                session,
                search_session_id=search_session_id,
            )
            if search_session is None:
                return
            await repo.update_session_status(
                session,
                search_session=search_session,
                status="running",
                result_count=0,
            )
            await session.commit()
            break
    except Exception as exc:
        await _mark_session_failed(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            error_code="search_status_update_failed",
            error_message=f"更新搜索状态失败: {str(exc)}",
        )
        logger.exception("search.mark_running_failed", search_session_id=search_session_id)
        return

    t0 = perf_counter()
    run_timeout_seconds = _SEARCH_RUN_TIMEOUT_SECONDS_BY_MODE.get(mode, 60)
    try:
        with start_span("search.agent", attributes={
            "search.notebook_id": notebook_id,
            "search.mode": mode,
            "search.session_id": search_session_id,
        }):
            response = await asyncio.wait_for(
                run_search_agent(
                    chat_model,
                    lite_model,
                    query=query.strip(),
                    notebook_id=notebook_id,
                    exa_api_key=exa_api_key,
                    tavily_api_key=tavily_api_key,
                    mode=mode,
                    notebook_title=notebook_title,
                    existing_article_urls=existing_article_urls,
                    notebook_article_summaries=notebook_article_summaries,
                    preferred_sites=preferred_sites,
                    max_results=max_results,
                    search_session_id=search_session_id,
                ),
                timeout=run_timeout_seconds,
            )
    except TimeoutError:
        elapsed_ms = round((perf_counter() - t0) * 1000, 2)
        observe_search_e2e(mode=mode, duration_ms=elapsed_ms)
        await _mark_session_failed(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            error_code="search_graph_timeout",
            error_message=f"搜索执行超时（>{run_timeout_seconds}s），请重试或切换模式",
        )
        logger.warning(
            "search.run_timeout",
            search_session_id=search_session_id,
            elapsed_ms=elapsed_ms,
            timeout_seconds=run_timeout_seconds,
        )
        return
    except Exception as exc:
        elapsed_ms = round((perf_counter() - t0) * 1000, 2)
        observe_search_e2e(mode=mode, duration_ms=elapsed_ms)
        await _mark_session_failed(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            error_code="search_graph_failed",
            error_message=str(exc),
        )
        logger.exception("search.run_failed", search_session_id=search_session_id, elapsed_ms=elapsed_ms)
        return

    elapsed_ms = round((perf_counter() - t0) * 1000, 2)

    provider_all_failed = bool((response.debug or {}).get("providerAllFailed"))
    if provider_all_failed and not response.items:
        await _mark_session_failed(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            error_code="search_provider_all_failed",
            error_message="搜索引擎全部调用失败，请稍后重试。",
        )
        observe_search_e2e(mode=mode, duration_ms=elapsed_ms)
        observe_search_empty_slate(mode=mode, reason="provider_all_failed")
        logger.warning(
            "search.provider_all_failed",
            search_session_id=search_session_id,
            mode=mode,
            elapsed_ms=elapsed_ms,
        )
        return

    debug_payload = response.debug or {}
    provider_failures = int(debug_payload.get("providerFailures") or 0)
    llm_unavailable = bool(debug_payload.get("llmScoreUnavailable"))
    result_status = "partial" if response.items and (provider_failures > 0 or llm_unavailable) else "completed"
    response.run.status = result_status

    try:
        async for session in get_session_manager().session():
            search_session = await repo.get_search_session_by_id(
                session,
                search_session_id=search_session_id,
            )
            if search_session is None:
                return
            result_ids = await repo.save_agent_search_results(
                session,
                search_session_id=search_session.id,
                cards=[item.model_dump(mode="json") for item in response.items],
            )
            for item, result_id in zip(response.items, result_ids):
                item.id = result_id

            await repo.update_session_status(
                session,
                search_session=search_session,
                status=result_status,
                result_count=len(response.items),
                completed_at=datetime.now(UTC),
            )
            await session.commit()
            break
    except Exception as exc:
        await _mark_session_failed(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            error_code="search_persist_failed",
            error_message=f"保存搜索结果失败: {str(exc)}",
        )
        logger.exception("search.persist_failed", search_session_id=search_session_id)
        return

    try:
        await _cache_response(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session_id,
            response=response,
            status=result_status,
        )
    except Exception:
        logger.warning("search.cache_write_failed", search_session_id=search_session_id, status="completed")

    # ========== metrics ==========
    observe_search_e2e(mode=mode, duration_ms=elapsed_ms)
    observe_search_slate_card_count(mode=mode, count=len(response.items))
    if not response.items:
        observe_search_empty_slate(mode=mode, reason="no_results")
    logger.info(
        "search.completed" if result_status == "completed" else "search.partial_completed",
        search_session_id=search_session_id,
        mode=mode,
        status=result_status,
        elapsed_ms=elapsed_ms,
        card_count=len(response.items),
    )


async def get_search_session(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> SearchResponse:
    cache_key = search_session_key(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    cached = await get_json(cache_key)
    if isinstance(cached, dict):
        cached_status = ((cached.get("run") or {}).get("status") or "").lower()
        if cached_status in {"completed", "partial", "failed", "expired", "cancelled"}:
            return SearchResponse(**cached)

    search_session = await repo.get_search_session(
        db,
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    now = datetime.now(UTC)
    is_expired = bool(search_session.expires_at and search_session.expires_at <= now)
    zombie_timeout_seconds = _SEARCH_SESSION_ZOMBIE_TIMEOUT_SECONDS_BY_MODE.get(
        search_session.mode or "",
        120,
    )
    is_zombie = (
        search_session.status in {"queued", "running"}
        and (now - search_session.created_at).total_seconds() > zombie_timeout_seconds
    )
    if is_expired:
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="expired",
            error_code="search_session_timeout",
            error_message="搜索会话已超时，请重试或切换模式",
            completed_at=now,
        )
        await db.commit()
    elif is_zombie:
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="failed",
            error_code="search_session_stale_timeout",
            error_message="搜索会话长时间未完成，请重新搜索",
            completed_at=now,
        )
        await db.commit()
        logger.warning(
            "search.session_stale_failed",
            search_session_id=search_session.id,
            status=search_session.status,
            mode=search_session.mode,
            age_seconds=(now - search_session.created_at).total_seconds(),
            timeout_seconds=zombie_timeout_seconds,
        )

    results: list[SearchResult] = []
    if search_session.status in {"completed", "partial", "running", "queued"}:
        results = await repo.list_search_results(db, search_session_id=search_session.id)

    response = _build_response_from_results(search_session, results)
    await _cache_response(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    return SearchResponse(**response.model_dump())


def _build_response_from_results(
    search_session: SearchSession,
    results: list[SearchResult],
) -> SearchResponsePayload:
    items = [_result_to_card(result) for result in results]
    return SearchResponsePayload(
        run=SearchRunView(
            id=search_session.id,
            notebookId=search_session.notebook_id,
            query=search_session.query,
            mode=search_session.mode,
            modeLabel=search_session.mode_label,
            status=search_session.status,
            currentRound=1,
            maxRounds=1,
            targetCount=search_session.result_count or len(items),
            elapsedMs=0,
        ),
        taskSpec={},
        recallSummary={},
        items=items,
        preferencesApplied={},
        debug=None,
    )


def _result_to_card(result: SearchResult) -> SearchResultCardView:
    payload = result.raw_payload_json or {}
    return SearchResultCardView(
        id=result.id,
        title=result.title,
        url=result.raw_url,
        domain=result.domain or "",
        sourceName=result.domain or "",
        sourceTypeBadge=payload.get("source_type_badge", ""),
        faviconUrl=result.favicon_url,
        authorityBadge=payload.get("authority_badge"),
        publishedAt=result.published_at,
        description=result.description or "",
        author=result.author,
        highlights=payload.get("highlights", []),
        whySelected=payload.get("why_selected", ""),
        importSuggestion=payload.get("import_suggestion", "optional"),
        finalScore=payload.get("final_score", 0.0),
        scoreBreakdown=payload.get("score_breakdown", {}),
        provider=payload.get("provider", "unknown"),
        queryFamily=payload.get("query_family", ""),
        preferredSiteHit=payload.get("preferred_site_hit", False),
        matchedPreferredSite=payload.get("matched_preferred_site"),
        duplicateRisk=payload.get("duplicate_risk", False),
        selectedReasonTags=payload.get("selected_reason_tags", []),
        displayRank=result.display_rank,
    )


async def _cache_response(
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
    response: SearchResponsePayload,
    status: str,
) -> None:
    settings = get_settings()
    ttl = (
        settings.cache_ttl_search_session_completed_seconds
        if status in {"completed", "partial", "failed", "expired", "cancelled"}
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


async def sweep_stale_search_sessions(*, limit: int = 200) -> int:
    """后台扫尾：把长时间未完成的 queued/running 会话标记为 failed。"""

    now = datetime.now(UTC)
    stale_count = 0
    async for session in get_session_manager().session():
        pending = await repo.list_pending_sessions_for_sweep(session, limit=limit)
        for item in pending:
            timeout_seconds = _SEARCH_SESSION_ZOMBIE_TIMEOUT_SECONDS_BY_MODE.get(item.mode or "", 120)
            age_seconds = (now - item.created_at).total_seconds()
            if age_seconds <= timeout_seconds:
                continue
            await repo.update_session_status(
                session,
                search_session=item,
                status="failed",
                error_code="search_session_stale_timeout",
                error_message="搜索会话长时间未完成，系统已自动结束，请重新搜索",
                completed_at=now,
            )
            stale_count += 1
            logger.warning(
                "search.session_stale_swept",
                search_session_id=item.id,
                mode=item.mode,
                age_seconds=age_seconds,
                timeout_seconds=timeout_seconds,
            )
        if stale_count > 0:
            await session.commit()
        return stale_count
    return stale_count


async def cancel_search_session(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> SearchResponse:
    search_session = await repo.get_search_session(
        db,
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    if search_session.status not in {"completed", "partial", "failed", "expired", "cancelled"}:
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="cancelled",
            error_code="search_cancelled_by_user",
            error_message="搜索已取消",
            completed_at=datetime.now(UTC),
        )
        await db.commit()

    results: list[SearchResult] = []
    if search_session.status in {"completed", "partial", "running", "queued", "cancelled"}:
        results = await repo.list_search_results(db, search_session_id=search_session.id)
    response = _build_response_from_results(search_session, results)
    response.run.status = search_session.status
    await _cache_response(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    return SearchResponse(**response.model_dump())
