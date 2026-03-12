from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.ai.chat.schemas import ChatRequest
from app.modules.ai.chat.service import reply, stream_reply
from app.modules.ai.summary.service import get_summary, stream_summary

router = APIRouter(tags=["ai"])


@router.post("/notebooks/{notebook_id}/articles/{article_id}/summary")
async def summary_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_summary(
        session,
        user=current_user,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    return success_response(item=item)


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
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/notebooks/{notebook_id}/chat")
async def chat_endpoint(
    notebook_id: str,
    payload: ChatRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await reply(
        session,
        user=current_user,
        notebook_id=notebook_id,
        conversation_id=payload.conversationId,
        article_id=payload.articleId,
        message=payload.message,
    )
    return success_response(item=item)


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
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
