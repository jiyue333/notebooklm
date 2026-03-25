from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.notes import repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.service import invalidate_notebook_detail_cache
from app.modules.notebooks.assembler import build_note_view


async def save_note(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    note_id: str | None,
    title: str | None,
    content: str | None,
    note_type: str | None,
    sources: int | None,
    tags: list[str] | None = None,
) -> dict:
    notebook = await notebooks_repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    normalized_title = title.strip() if title and title.strip() else "无标题笔记"
    normalized_content = content or ""
    normalized_type = note_type or "笔记"
    normalized_sources = sources if sources is not None else 0
    normalized_tags = [tag.strip() for tag in (tags or []) if str(tag).strip()][:8]

    if note_id is None:
        note = await repo.create_note(
            session,
            notebook_id=notebook_id,
            title=normalized_title,
            content_markdown=normalized_content,
            note_type=normalized_type,
            source_count=normalized_sources,
            tags_json=normalized_tags,
        )
    else:
        note = await repo.get_note(
            session,
            user_id=user_id,
            notebook_id=notebook_id,
            note_id=note_id,
        )
        if note is None:
            raise AppError(404, "未找到对应笔记", code="note_not_found")
        note.title = normalized_title
        note.content_markdown = normalized_content
        note.note_type = normalized_type
        note.source_count = normalized_sources
        note.tags_json = normalized_tags

    await session.commit()
    await session.refresh(note)
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return build_note_view(note)


async def delete_note(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    note_id: str,
) -> None:
    note = await repo.get_note(session, user_id=user_id, notebook_id=notebook_id, note_id=note_id)
    if note is None:
        raise AppError(404, "未找到对应笔记", code="note_not_found")
    await repo.delete_note(session, note)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)


async def export_note_markdown(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    note_id: str,
) -> tuple[str, str]:
    note = await repo.get_note(session, user_id=user_id, notebook_id=notebook_id, note_id=note_id)
    if note is None:
        raise AppError(404, "未找到对应笔记", code="note_not_found")
    filename = f"{note.title or 'note'}.md"
    return filename, note.content_markdown
