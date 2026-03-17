"""搜索服务 – agent 搜索执行、会话查询、缓存。"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

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
from app.modules.agent.search.schemas import (
    SearchCardView,
    SearchResponse,
    SearchSessionView,
)

logger = structlog.get_logger(__name__)


# ── public API ─────────────────────────────────────────────────────────────

async def start_agent_search(
    db: AsyncSession,
    *,
    user,
    notebook_id: str,
    query: str,
    mode: str = "auto",
    max_results: int = 15,
    exa_api_key: str,
    notebook_title: str = "",
    existing_article_urls: list[str] | None = None,
    existing_article_titles: list[str] | None = None,
) -> SearchResponse:
    """执行 agent 搜索，并保存搜索会话与结果。"""

    # ========== phase 1 初始化 ==========
    t0 = perf_counter()

    chat_model = build_user_chat_model(user)
    lite_model = build_lite_llm()

    if chat_model is None:
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")

    # ========== phase 2 创建搜索会话 ==========
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
        },
        provider_name="agent",
    )
    await db.commit()
    await db.refresh(search_session)

    await repo.update_session_status(db, search_session=search_session, status="running")
    await db.commit()

    # ========== phase 3 执行搜索编排 ==========
    try:
        result = await run_search_agent(
            chat_model,
            lite_model,
            query=query.strip(),
            exa_api_key=exa_api_key,
            exa_mode=mode,
            notebook_title=notebook_title,
            existing_article_titles=existing_article_titles,
            existing_article_urls=existing_article_urls,
            max_results=max_results,
        )

        # ========== phase 4 保存结果 ==========
        elapsed_ms = round((perf_counter() - t0) * 1000, 2)
        cards_data = result.get("cards", [])
        completed_at = datetime.now(UTC)

        result_ids = await _persist_results(
            db, search_session=search_session, cards=cards_data,
        )
        await repo.update_session_status(
            db,
            search_session=search_session,
            status="completed",
            result_count=len(cards_data),
            completed_at=completed_at,
        )
        await db.commit()

        logger.info(
            "search.completed",
            search_session_id=search_session.id,
            card_count=len(cards_data),
            raw_count=result.get("raw_count", 0),
            elapsed_ms=elapsed_ms,
        )

        for card, rid in zip(cards_data, result_ids):
            card["_id"] = rid

        response = _build_response_from_cards(search_session, cards_data, meta={
            "provider": "agent",
            "elapsedMs": elapsed_ms,
            "rawCount": result.get("raw_count", 0),
            "scoredCount": result.get("scored_count", 0),
            "intent": result.get("intent", {}),
        })
        await _cache_response(
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
            response=response,
            status=search_session.status,
        )
        return response

    except Exception as exc:
        # ========== phase 4 失败处理 ==========
        error_msg = str(exc)[:500]
        await db.rollback()

        ss = await repo.get_search_session_by_id(
            db, search_session_id=search_session.id,
        ) or search_session
        await repo.update_session_status(
            db,
            search_session=ss,
            status="failed",
            error_code="agent_search_failed",
            error_message=error_msg,
            completed_at=datetime.now(UTC),
        )
        await db.commit()

        logger.exception(
            "search.failed",
            search_session_id=search_session.id,
            error=error_msg,
        )
        raise AppError(502, "智能搜索执行失败", code="agent_search_failed")


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

    response = _build_response_from_results(search_session, results)
    await _cache_response(
        user_id=user_id,
        notebook_id=notebook_id,
        search_session_id=search_session.id,
        response=response,
        status=search_session.status,
    )
    return response


# ── 持久化辅助 ──────────────────────────────────────────────────────────────

async def _persist_results(
    db: AsyncSession,
    *,
    search_session: SearchSession,
    cards: list[dict],
) -> list[str]:
    """把搜索卡片写入 search_results 表。"""
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


# ── 响应构造 ───────────────────────────────────────────────────────────────

def _session_view(ss: SearchSession) -> SearchSessionView:
    return SearchSessionView(
        searchSessionId=ss.id,
        mode=ss.mode,
        modeLabel=ss.mode_label,
        status=ss.status,
        execution=ss.execution_mode,
    )


def _build_response_from_cards(
    ss: SearchSession,
    cards: list[dict],
    *,
    meta: dict | None = None,
) -> SearchResponse:
    """start_agent_search 用：从 card dict 构造响应。"""
    return SearchResponse(
        item=_session_view(ss),
        items=[_card_to_view(c) for c in cards],
        meta=meta or {"provider": "agent"},
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


def _build_response_from_results(
    ss: SearchSession,
    results: list[SearchResult],
    *,
    meta: dict | None = None,
) -> SearchResponse:
    """get_search_session 用：从 ORM 对象构造响应。"""
    return SearchResponse(
        item=_session_view(ss),
        items=[_result_to_card_view(r) for r in results],
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
