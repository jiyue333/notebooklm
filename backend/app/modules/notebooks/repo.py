from __future__ import annotations

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notebooks.models import Notebook


def _owned_notebook_query(user_id: str) -> Select[tuple[Notebook]]:
    return select(Notebook).where(Notebook.user_id == user_id)


async def list_notebooks(
    session: AsyncSession,
    *,
    user_id: str,
    query: str | None = None,
) -> list[Notebook]:
    stmt = _owned_notebook_query(user_id)
    if query:
        stmt = stmt.where(Notebook.title.ilike(f"%{query}%"))
    stmt = stmt.order_by(desc(Notebook.updated_at), desc(Notebook.created_at))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> Notebook | None:
    result = await session.execute(
        _owned_notebook_query(user_id).where(Notebook.id == notebook_id)
    )
    return result.scalar_one_or_none()


async def create_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
    emoji: str | None,
    color: str | None,
) -> Notebook:
    notebook = Notebook(user_id=user_id, title=title, emoji=emoji, color=color)
    session.add(notebook)
    await session.flush()
    return notebook


async def delete_notebook(session: AsyncSession, notebook: Notebook) -> None:
    await session.delete(notebook)
