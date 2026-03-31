"""AI 接口路由：摘要、聊天、搜索。"""

from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from typing import AsyncIterator, Literal
from urllib.parse import urlparse

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.api.sse import build_sse_error_payload, encode_sse_event
from app.infra.cache import get_json, search_context_key, set_json
from app.modules.agent.chat.service import list_notebook_conversations, remove_notebook_conversation, stream_message
from app.modules.agent.search import repo as search_repo
from app.modules.agent.summary.service import (
    cache_temporary_unavailable_summary,
    generate_summary,
    list_notebook_summaries,
    normalize_summary_language,
)
from app.modules.notebooks import repo as notebooks_repo
from app.modules.settings.runtime import (
    get_merged_user_settings,
    resolve_preferred_sites,
    resolve_search_api_key,
    resolve_tavily_api_key,
)
from app.modules.agent.search.schemas import SearchRequest, SearchResponse
from app.modules.agent.search.service import (
    cancel_search_session,
    get_latest_search_session,
    get_search_session,
    start_agent_search,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_SEARCH_RATE_WINDOW_SECONDS = 20
_SEARCH_RATE_MAX_REQUESTS = 6
_SEARCH_CONTEXT_CACHE_TTL_SECONDS = 90
_SUMMARY_STREAM_MAX_CONCURRENCY = 3
_search_request_buckets: dict[str, deque[float]] = defaultdict(deque)
_search_rate_lock = asyncio.Lock()
_summary_stream_semaphore = asyncio.Semaphore(_SUMMARY_STREAM_MAX_CONCURRENCY)


def _normalize_existing_url(url: str | None) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _normalize_user_text(value: str) -> str:
    sanitized = value.replace("\x00", " ").strip()
    return re.sub(r"\s+", " ", sanitized)


async def _enforce_search_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    async with _search_rate_lock:
        bucket = _search_request_buckets[user_id]
        while bucket and (now - bucket[0]) > _SEARCH_RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= _SEARCH_RATE_MAX_REQUESTS:
            raise AppError(429, "搜索请求过于频繁，请稍后再试", code="search_rate_limited")
        bucket.append(now)


def _tokenize_query(value: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", (value or "").lower()))


def _prioritize_notebook_summaries(query: str, summaries: list[dict], *, limit: int = 10) -> list[dict]:
    if not summaries:
        return []
    query_terms = _tokenize_query(query)
    if not query_terms:
        return summaries[:limit]
    ranked: list[tuple[float, int, dict]] = []
    for idx, item in enumerate(summaries):
        title = str(item.get("title") or "").lower()
        summary_text = str(item.get("summaryText") or "").lower()
        haystack = f"{title} {summary_text}"
        overlap = sum(1 for token in query_terms if token in haystack)
        density = overlap / max(len(query_terms), 1)
        # list_articles_by_notebook 默认按创建时间倒序，索引越靠前越新
        recency_bonus = max(0.0, 1.0 - idx * 0.05)
        score = density * 0.8 + recency_bonus * 0.2
        ranked.append((score, idx, item))
    ranked.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    return [item for _, _, item in ranked[:limit]]


class AiEventRequest(BaseModel):
    operation: Literal["chat", "summary"]
    action: Literal["follow_up", "citation_open", "answer_copy", "summary_copy"]
    route: str | None = None
    articleId: str | None = None
    conversationId: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    articleId: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    recentHighlights: list[dict] = Field(default_factory=list)
    recentTurns: list[dict] = Field(default_factory=list)
    readingCursor: dict | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = _normalize_user_text(value)
        if not normalized:
            raise ValueError("message 不能为空")
        return normalized


class TranslateRequest(BaseModel):
    targetLanguage: str | None = None




@router.get("/notebooks/{notebook_id}/conversations")
async def list_conversations_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    return success_response(items=await list_notebook_conversations(session, user_id=current_user.id, notebook_id=notebook_id))


@router.delete("/notebooks/{notebook_id}/conversations/{conversation_id}")
async def delete_conversation_endpoint(
    notebook_id: str,
    conversation_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await remove_notebook_conversation(session, user_id=current_user.id, notebook_id=notebook_id, conversation_id=conversation_id)
    return {"success": True}


@router.post("/notebooks/{notebook_id}/articles/{article_id}/translate")
async def translate_article_endpoint(
    notebook_id: str,
    article_id: str,
    payload: TranslateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(session, user_id=current_user.id, notebook_id=notebook_id, article_id=article_id)
    if article is None or not article.clean_markdown:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    merged_settings = get_merged_user_settings(current_user)
    target_language = payload.targetLanguage or merged_settings.get("outputLanguage") or "中文"
    model = stream_message.__globals__['build_user_chat_model'](current_user)
    if model is None:
        raise AppError(422, '请先配置聊天模型', code='model_config_required')
    result = await model.ainvoke([
        SystemMessage(content=f"请把下列文章翻译为{target_language}，保持原有 Markdown 段落结构。只输出译文。"),
        HumanMessage(content=article.clean_markdown[:16000]),
    ])
    return success_response(item={"translatedContent": (result.content or '').strip(), "targetLanguage": target_language})

@router.post("/notebooks/{notebook_id}/ai/events")
async def ai_event_endpoint(
    notebook_id: str,
    payload: AiEventRequest,
    current_user=Depends(current_user_dep),
):
    return success_response(item={"accepted": True})


@router.post("/notebooks/{notebook_id}/articles/{article_id}/summary/stream")
async def summary_stream_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        article = None
        output_language = "auto"
        try:
            article = await notebooks_repo.get_article(
                session,
                user_id=current_user.id,
                notebook_id=notebook_id,
                article_id=article_id,
            )
            if article is None:
                yield build_sse_error_payload(
                    AppError(404, "未找到对应文章", code="article_not_found"),
                    fallback_message="文章不存在", fallback_code="article_not_found",
                )
                return
            if not article.clean_markdown:
                yield build_sse_error_payload(
                    AppError(422, "文章尚未完成解析", code="article_not_ready"),
                    fallback_message="文章未就绪", fallback_code="article_not_ready",
                )
                return

            merged_settings = get_merged_user_settings(current_user)
            output_language = normalize_summary_language(merged_settings.get("outputLanguage"))
            token_queue: asyncio.Queue[str] = asyncio.Queue()

            async def _on_token(piece: str) -> None:
                if piece:
                    await token_queue.put(piece)

            acquired = False
            try:
                await asyncio.wait_for(_summary_stream_semaphore.acquire(), timeout=2)
                acquired = True
            except asyncio.TimeoutError:
                yield build_sse_error_payload(
                    AppError(429, "摘要请求较多，请稍后重试", code="summary_busy"),
                    fallback_message="摘要请求较多，请稍后重试",
                    fallback_code="summary_busy",
                    logger=logger,
                    log_event="ai.summary.busy",
                )
                logger.warning("ai.summary.concurrent_limited", notebook_id=notebook_id, article_id=article_id)
                return

            streamed_len = 0
            try:
                task = asyncio.create_task(generate_summary(
                    session,
                    article_id=article.id,
                    title=article.title,
                    clean_markdown=article.clean_markdown,
                    language=output_language,
                    user=current_user,
                    token_sink=_on_token,
                ))

                while True:
                    if task.done() and token_queue.empty():
                        break
                    try:
                        token = await asyncio.wait_for(token_queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    if not token:
                        continue
                    streamed_len += len(token)
                    yield encode_sse_event("token", {"text": token})

                result = await task
            finally:
                if acquired:
                    _summary_stream_semaphore.release()

            summary_text = str(result.get("summary_text", "") or "").strip()
            temporary_unavailable = bool(result.get("temporaryUnavailable", False))
            if not summary_text:
                try:
                    summary_text = await cache_temporary_unavailable_summary(
                        article_id=article.id,
                        title=article.title,
                        clean_markdown=article.clean_markdown or "",
                        language=output_language,
                        user=current_user,
                    )
                    temporary_unavailable = True
                except Exception:
                    logger.warning(
                        "ai.summary.temp_unavailable_cache_failed",
                        notebook_id=notebook_id,
                        article_id=article_id,
                    )
                    summary_text = "摘要服务暂时不可用，请 1 分钟后重试。"
                    temporary_unavailable = True
            if not streamed_len and summary_text:
                yield encode_sse_event("token", {"text": summary_text})
            yield encode_sse_event("done", {
                "summaryText": summary_text,
                "cached": result.get("cached", False),
                "language": output_language,
                "temporaryUnavailable": temporary_unavailable,
            })
        except Exception as exc:
            if article is not None and (article.clean_markdown or "").strip():
                try:
                    summary_text = await cache_temporary_unavailable_summary(
                        article_id=article.id,
                        title=article.title,
                        clean_markdown=article.clean_markdown or "",
                        language=output_language,
                        user=current_user,
                    )
                    yield encode_sse_event("done", {
                        "summaryText": summary_text,
                        "cached": False,
                        "language": output_language,
                        "temporaryUnavailable": True,
                    })
                    return
                except Exception:
                    logger.warning(
                        "ai.summary.temp_unavailable_emit_failed",
                        notebook_id=notebook_id,
                        article_id=article_id,
                    )
            yield build_sse_error_payload(
                exc, fallback_message="摘要生成失败", fallback_code="summary_failed",
                logger=logger, log_event="ai.summary.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/notebooks/{notebook_id}/summaries")
async def notebook_summaries_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    notebook = await notebooks_repo.get_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应笔记本", code="notebook_not_found")

    articles = await notebooks_repo.list_articles_by_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    merged_settings = get_merged_user_settings(current_user)
    output_language = normalize_summary_language(merged_settings.get("outputLanguage"))
    summaries = await list_notebook_summaries(
        session,
        articles=articles,
        user=current_user,
        language=output_language,
    )
    return success_response(items=summaries)


@router.post("/notebooks/{notebook_id}/chat/stream")
async def chat_stream_endpoint(
    notebook_id: str,
    payload: ChatRequest,
    request: Request,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=2)

        async def _produce() -> None:
            try:
                async for event in stream_message(
                    session,
                    user_id=current_user.id,
                    notebook_id=notebook_id,
                    question=payload.message,
                    article_id=payload.articleId,
                    conversation_id=payload.conversationId,
                    recent_highlights=payload.recentHighlights,
                    recent_turns=payload.recentTurns,
                    user=current_user,
                ):
                    await queue.put({"type": "event", "payload": event})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await queue.put({"type": "error", "payload": exc})
            finally:
                await queue.put({"type": "done"})

        producer = asyncio.create_task(_produce())
        client_disconnected = False
        stream_cancelled = False
        try:
            try:
                while True:
                    if await request.is_disconnected():
                        client_disconnected = True
                        break
                    try:
                        item = await asyncio.wait_for(queue.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue

                    item_type = item.get("type")
                    if item_type == "done":
                        break
                    if item_type == "error":
                        exc = item.get("payload")
                        yield build_sse_error_payload(
                            exc, fallback_message="聊天回复失败", fallback_code="chat_failed",
                            logger=logger, log_event="ai.chat.stream_error",
                        )
                        break

                    event = item.get("payload") or {}
                    if event.get("type") == "token":
                        yield encode_sse_event("token", {"text": event.get("text", "")})
                    elif event.get("type") == "done":
                        yield encode_sse_event("done", event.get("data", {}))
            except asyncio.CancelledError:
                stream_cancelled = True
                raise
        finally:
            if client_disconnected or stream_cancelled:
                logger.info(
                    "ai.chat.stream_client_disconnected",
                    user_id=current_user.id,
                    notebook_id=notebook_id,
                    conversation_id=payload.conversationId,
                )
            if (client_disconnected or stream_cancelled) and not producer.done():
                producer.cancel()
            try:
                await producer
            except asyncio.CancelledError:
                pass

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Search ─────────────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/search")
async def search_sources_endpoint(
    notebook_id: str,
    payload: SearchRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    await _enforce_search_rate_limit(current_user.id)

    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    exa_api_key, _key_source = resolve_search_api_key(current_user)

    active_sessions = await search_repo.count_active_sessions(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    if active_sessions >= 3:
        raise AppError(429, "当前搜索任务过多，请等待现有任务完成后再试", code="search_too_many_active_sessions")

    context_key = search_context_key(user_id=current_user.id, notebook_id=notebook_id)
    context_payload = await get_json(context_key)
    existing_urls: list[str]
    notebook_summaries: list[dict]
    if isinstance(context_payload, dict):
        cached_urls = context_payload.get("existingUrls")
        cached_summaries = context_payload.get("notebookSummaries")
        if isinstance(cached_urls, list) and isinstance(cached_summaries, list):
            existing_urls = [str(item) for item in cached_urls if str(item or "").strip()]
            notebook_summaries = [item for item in cached_summaries if isinstance(item, dict)]
        else:
            context_payload = None
    if not isinstance(context_payload, dict):
        existing_articles = await notebooks_repo.list_articles_by_notebook(
            session,
            user_id=current_user.id,
            notebook_id=notebook_id,
        )
        existing_urls = [
            article.normalized_url or _normalize_existing_url(article.source_url)
            for article in existing_articles
            if (article.normalized_url or article.source_url)
        ]
        notebook_summaries = await list_notebook_summaries(
            session,
            articles=existing_articles,
            user=current_user,
            language="auto",
            backfill_limit=0,
        )
        await set_json(
            context_key,
            {
                "existingUrls": existing_urls,
                "notebookSummaries": notebook_summaries,
            },
            ttl_seconds=_SEARCH_CONTEXT_CACHE_TTL_SECONDS,
        )
    notebook_summaries = _prioritize_notebook_summaries(payload.query, notebook_summaries, limit=10)

    preferred_sites = resolve_preferred_sites(current_user)
    tavily_api_key, _tavily_source = resolve_tavily_api_key(current_user)
    if not exa_api_key and not tavily_api_key:
        raise AppError(422, "请先在设置里配置 Exa Key 或系统 Tavily Key", code="search_api_key_required")

    return await start_agent_search(
        session,
        user=current_user,
        notebook_id=notebook_id,
        query=payload.query,
        mode=payload.mode,
        max_results=payload.maxResults,
        exa_api_key=exa_api_key,
        tavily_api_key=tavily_api_key,
        notebook_title=notebook.title or "",
        existing_article_urls=existing_urls,
        notebook_article_summaries=notebook_summaries,
        preferred_sites=preferred_sites,
    )


@router.get("/notebooks/{notebook_id}/search-sessions/latest")
async def get_latest_search_session_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_latest_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    return success_response(item=item.model_dump(mode="json") if item else None)


@router.get("/notebooks/{notebook_id}/search-sessions/{search_session_id}")
async def get_search_session_endpoint(
    notebook_id: str,
    search_session_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    return await get_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )


@router.post("/notebooks/{notebook_id}/search-sessions/{search_session_id}/cancel")
async def cancel_search_session_endpoint(
    notebook_id: str,
    search_session_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    return await cancel_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
