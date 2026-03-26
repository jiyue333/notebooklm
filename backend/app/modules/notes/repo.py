from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notes.models import Note
from app.modules.notebooks.models import Notebook


async def list_notes(session: AsyncSession, *, user_id: str, notebook_id: str) -> list[Note]:
    result = await session.execute(
        select(Note)
        .join(Notebook, Notebook.id == Note.notebook_id)
        .where(Note.notebook_id == notebook_id, Notebook.user_id == user_id)
        .order_by(desc(Note.updated_at), desc(Note.created_at))
    )
    return list(result.scalars().all())


async def get_note(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    note_id: str,
) -> Note | None:
    result = await session.execute(
        select(Note)
        .join(Notebook, Notebook.id == Note.notebook_id)
        .where(Note.id == note_id, Note.notebook_id == notebook_id, Notebook.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_note(
    session: AsyncSession,
    *,
    notebook_id: str,
    title: str,
    content_markdown: str,
    note_type: str,
    source_count: int,
    tags_json: list[str] | None = None,
) -> Note:
    note = Note(
        notebook_id=notebook_id,
        title=title,
        content_markdown=content_markdown,
        note_type=note_type,
        source_count=source_count,
        tags_json=tags_json,
    )
    session.add(note)
    await session.flush()
    return note


async def delete_note(session: AsyncSession, note: Note) -> None:
    await session.delete(note)
