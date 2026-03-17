"""AI API endpoints – summary and chat (SSE streaming).

POST /notebooks/{id}/ai/events                      – record user event
POST /notebooks/{id}/articles/{aid}/summary/stream   – SSE stream summary
POST /notebooks/{id}/chat/stream                     – SSE stream chat
"""

from __future__ import annotations

from typing import AsyncIterator, Literal

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.api.sse import build_sse_error_payload, encode_sse_event
from app.modules.agent.chat.service import send_message
from app.modules.agent.summary.service import generate_summary
from app.modules.notebooks import repo as notebooks_repo

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


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

            result = await generate_summary(
                session,
                article_id=article.id,
                title=article.title,
                clean_markdown=article.clean_markdown,
                language="zh",
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
            result = await send_message(
                session,
                user_id=current_user.id,
                notebook_id=notebook_id,
                question=payload.message,
                article_id=payload.articleId,
                conversation_id=payload.conversationId,
                user=current_user,
            )

            answer = result.get("answer_text", "")
            yield encode_sse_event("token", {"text": answer})
            yield encode_sse_event("done", {
                "route": result.get("route", "general"),
                "routeBadge": result.get("route_badge", "General answer"),
                "answer": answer,
                "evidence": result.get("evidence", []),
                "conversationId": result.get("conversation_id"),
                "messageId": result.get("message_id"),
            })
        except Exception as exc:
            yield build_sse_error_payload(
                exc, fallback_message="聊天回复失败", fallback_code="chat_failed",
                logger=logger, log_event="ai.chat.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
