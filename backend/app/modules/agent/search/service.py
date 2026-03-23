"""搜索服务：加载上下文、执行搜索图、持久化与缓存。"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.ai.lite_models import build_lite_llm
from app.infra.cache import get_json, search_session_key, set_json
from app.modules.agent.search import repo
from app.modules.agent.search.graph import run_search_agent
from app.modules.agent.search.models import SearchResult, SearchSession
from app.modules.agent.search.schemas import SearchResponse
from app.modules.agent.search.state import SearchResponsePayload, SearchResultCardView, SearchRunView

logger = structlog.get_logger(__name__)


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

    chat_model = build_user_chat_model(user)
    lite_model = build_lite_llm()
    if chat_model is None:
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")

    if not exa_api_key and not tavily_api_key:
        raise AppError(422, "请先配置至少一个搜索引擎 Key", code="search_provider_key_required")

    search_session = await repo.create_search_session(
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
            "preferredSites": preferred_sites or [],
        },
        provider_name="langgraph_search",
    )
    await db.commit()
    await db.refresh(search_session)

    try:
        response = await run_search_agent(
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
            search_session_id=search_session.id,
        )
    except Exception as exc:
        await db.rollback()
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="failed",
            error_code="search_graph_failed",
            error_message=str(exc)[:500],
            completed_at=datetime.now(UTC),
        )
        await db.commit()
        logger.exception("search.run_failed", search_session_id=search_session.id)
        raise AppError(502, "智能搜索执行失败", code="search_graph_failed")

    result_ids = await repo.save_agent_search_results(
        db,
        search_session_id=search_session.id,
        cards=[item.model_dump(mode="json") for item in response.items],
    )
    for item, result_id in zip(response.items, result_ids):
        item.id = result_id

    await repo.update_session_status(
        db,
        search_session=search_session,
        status="completed",
        result_count=len(response.items),
        completed_at=datetime.now(UTC),
    )
    await db.commit()

    await _cache_response(
        user_id=user.id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status="completed",
    )
    return SearchResponse(**response.model_dump())


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
        return SearchResponse(**cached)

    search_session = await repo.get_search_session(
        db,
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    results: list[SearchResult] = []
    if search_session.status == "completed":
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
