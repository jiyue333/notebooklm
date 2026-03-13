from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.ai.chat.service import stream_reply
from app.modules.ai.summary.service import stream_summary
from app.modules.tracker import record_ai_user_event

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

AiEventOperation = Literal["chat", "summary"]
AiEventAction = Literal["follow_up", "citation_open", "answer_copy", "summary_copy"]
AiEventRoute = Literal["CURRENT_ARTICLE", "RELATED_ARTICLES", "EVIDENCE_LOOKUP", "GENERAL", "none"]


class AiEventRequest(BaseModel):
    operation: AiEventOperation
    action: AiEventAction
    route: AiEventRoute | None = None
    articleId: str | None = None
    conversationId: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    articleId: str | None = None
    message: str = Field(min_length=1)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/notebooks/{notebook_id}/ai/events")
async def ai_event_endpoint(
    notebook_id: str,
    payload: AiEventRequest,
    current_user=Depends(current_user_dep),
):
    await record_ai_user_event(
        user=current_user,
        notebook_id=notebook_id,
        operation=payload.operation,
        action=payload.action,
        route=payload.route,
        article_id=payload.articleId,
        conversation_id=payload.conversationId,
    )
    return success_response(item={"accepted": True})


@router.post("/notebooks/{notebook_id}/articles/{article_id}/summary/stream")
async def summary_stream_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    stream = await stream_summary(
        session,
        user=current_user,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/notebooks/{notebook_id}/chat/stream")
async def chat_stream_endpoint(
    notebook_id: str,
    payload: ChatRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    stream = await stream_reply(
        session,
        user=current_user,
        notebook_id=notebook_id,
        conversation_id=payload.conversationId,
        article_id=payload.articleId,
        message=payload.message,
    )
    return StreamingResponse(stream, media_type="text/event-stream", headers=_SSE_HEADERS)
