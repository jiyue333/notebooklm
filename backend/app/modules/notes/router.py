from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.notes.schemas import NoteUpsertRequest
from app.modules.notes.service import delete_note, save_note

router = APIRouter(tags=["notes"])


@router.post("/notebooks/{notebook_id}/notes")
async def create_note_endpoint(
    notebook_id: str,
    payload: NoteUpsertRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await save_note(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        note_id=None,
        title=payload.title,
        content=payload.content,
        note_type=payload.type,
        sources=payload.sources,
    )
    return success_response(item=item)


@router.put("/notebooks/{notebook_id}/notes/{note_id}")
async def update_note_endpoint(
    notebook_id: str,
    note_id: str,
    payload: NoteUpsertRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await save_note(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        note_id=note_id,
        title=payload.title,
        content=payload.content,
        note_type=payload.type,
        sources=payload.sources,
    )
    return success_response(item=item)


@router.delete("/notebooks/{notebook_id}/notes/{note_id}")
async def delete_note_endpoint(
    notebook_id: str,
    note_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await delete_note(session, user_id=current_user.id, notebook_id=notebook_id, note_id=note_id)
    return {"success": True}
