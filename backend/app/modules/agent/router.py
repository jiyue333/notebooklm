"""AI 接口路由：摘要、聊天、搜索。"""

from __future__ import annotations

from typing import AsyncIterator, Literal
from urllib.parse import urlparse

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.api.sse import build_sse_error_payload, encode_sse_event
from app.modules.agent.chat.service import list_notebook_conversations, remove_notebook_conversation, stream_message
from app.modules.agent.summary.service import list_notebook_summaries
from app.modules.agent.summary.service import generate_summary
from app.modules.notebooks import repo as notebooks_repo
from app.modules.settings.runtime import resolve_preferred_sites, resolve_search_api_key, resolve_tavily_api_key
from app.modules.agent.search.schemas import SearchRequest, SearchResponse
from app.modules.agent.search.service import get_search_session, start_agent_search

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _normalize_existing_url(url: str | None) -> str:
    raw = (url or "").strip().lower()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


class AiEventRequest(BaseModel):
    operation: Literal["chat", "summary"]
    action: Literal["follow_up", "citation_open", "answer_copy", "summary_copy"]
    route: str | None = None
    articleId: str | None = None
    conversationId: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    articleId: str | None = None
    message: str = Field(min_length=1)


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
    target_language = payload.targetLanguage or (getattr(current_user, 'settings_json', {}) or {}).get('outputLanguage') or '中文'
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

            output_language = (getattr(current_user, "settings_json", {}) or {}).get("outputLanguage") or "中文"
            result = await generate_summary(
                session,
                article_id=article.id,
                title=article.title,
                clean_markdown=article.clean_markdown,
                language=output_language,
                user=current_user,
            )

            summary_text = result.get("summary_text", "")
            yield encode_sse_event("token", {"text": summary_text})
            yield encode_sse_event("done", {
                "summaryText": summary_text,
                "cached": result.get("cached", False),
            })
        except Exception as exc:
            yield build_sse_error_payload(
                exc, fallback_message="摘要生成失败", fallback_code="summary_failed",
                logger=logger, log_event="ai.summary.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/notebooks/{notebook_id}/chat/stream")
async def chat_stream_endpoint(
    notebook_id: str,
    payload: ChatRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        try:
            async for event in stream_message(
                session,
                user_id=current_user.id,
                notebook_id=notebook_id,
                question=payload.message,
                article_id=payload.articleId,
                conversation_id=payload.conversationId,
                user=current_user,
            ):
                if event["type"] == "token":
                    yield encode_sse_event("token", {"text": event["text"]})
                elif event["type"] == "done":
                    yield encode_sse_event("done", event["data"])
        except Exception as exc:
            yield build_sse_error_payload(
                exc, fallback_message="聊天回复失败", fallback_code="chat_failed",
                logger=logger, log_event="ai.chat.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Search ─────────────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/search")
async def search_sources_endpoint(
    notebook_id: str,
    payload: SearchRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    exa_api_key, _key_source = resolve_search_api_key(current_user)

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
    notebook_summaries = await list_notebook_summaries(session, articles=existing_articles)
    preferred_sites = resolve_preferred_sites(current_user)
    tavily_api_key, _tavily_source = resolve_tavily_api_key()
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
