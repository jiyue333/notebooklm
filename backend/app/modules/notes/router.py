from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.notes.schemas import NoteUpsertRequest
from app.modules.notes.service import delete_note, export_note_markdown, save_note

router = APIRouter(tags=["notes"])


def _build_content_disposition(filename: str) -> str:
    normalized = (filename or "note.md").strip() or "note.md"
    if not normalized.lower().endswith(".md"):
        normalized = f"{normalized}.md"
    ascii_base = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._-")
    if not ascii_base or ascii_base.lower() in {"md", ".md"}:
        ascii_base = "note"
    ascii_fallback = ascii_base if ascii_base.lower().endswith(".md") else f"{ascii_base}.md"
    encoded = quote(normalized, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


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
        tags=payload.tags,
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
        tags=payload.tags,
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



@router.get("/notebooks/{notebook_id}/notes/{note_id}/export")
async def export_note_endpoint(
    notebook_id: str,
    note_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    filename, content = await export_note_markdown(session, user_id=current_user.id, notebook_id=notebook_id, note_id=note_id)
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": _build_content_disposition(filename)},
    )
