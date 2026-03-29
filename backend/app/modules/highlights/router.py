from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.highlights.schemas import HighlightCreateRequest, HighlightUpdateRequest
from app.modules.highlights.service import (
    create_article_highlight,
    delete_article_highlight,
    list_article_highlights,
    update_article_highlight,
)

router = APIRouter(tags=["highlights"])


@router.get("/notebooks/{notebook_id}/articles/{article_id}/highlights")
async def list_article_highlights_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items = await list_article_highlights(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    return success_response(items=items)


@router.post("/notebooks/{notebook_id}/articles/{article_id}/highlights")
async def create_article_highlight_endpoint(
    notebook_id: str,
    article_id: str,
    payload: HighlightCreateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await create_article_highlight(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
        text=payload.text,
        color=payload.color,
        comment=payload.comment,
        start_offset=payload.startOffset,
        end_offset=payload.endOffset,
        occurrence_index=payload.occurrenceIndex,
    )
    return success_response(item=item)


@router.patch("/notebooks/{notebook_id}/articles/{article_id}/highlights/{highlight_id}")
async def update_article_highlight_endpoint(
    notebook_id: str,
    article_id: str,
    highlight_id: str,
    payload: HighlightUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await update_article_highlight(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
        highlight_id=highlight_id,
        color=payload.color,
        comment=payload.comment,
    )
    return success_response(item=item)


@router.delete("/notebooks/{notebook_id}/articles/{article_id}/highlights/{highlight_id}")
async def delete_article_highlight_endpoint(
    notebook_id: str,
    article_id: str,
    highlight_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await delete_article_highlight(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
        highlight_id=highlight_id,
    )
    return {"success": True}

