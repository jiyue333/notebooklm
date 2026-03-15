from __future__ import annotations

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from collections import defaultdict

from sqlalchemy import func

from app.modules.notebooks.models import Article, Notebook


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


# ── Article queries ────────────────────────────────────────────────────────

async def list_articles_by_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> list[Article]:
    result = await session.execute(
        select(Article)
        .where(Article.user_id == user_id, Article.notebook_id == notebook_id)
        .order_by(Article.created_at.desc())
    )
    return list(result.scalars().all())


async def count_articles_by_notebook_ids(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_ids: list[str],
) -> dict[str, int]:
    if not notebook_ids:
        return {}
    result = await session.execute(
        select(Article.notebook_id, func.count(Article.id))
        .where(Article.user_id == user_id, Article.notebook_id.in_(notebook_ids))
        .group_by(Article.notebook_id)
    )
    counts: dict[str, int] = defaultdict(int)
    for notebook_id, count in result.all():
        counts[notebook_id] = count
    return dict(counts)


async def get_article(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
) -> Article | None:
    result = await session.execute(
        select(Article).where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
            Article.id == article_id,
        )
    )
    return result.scalar_one_or_none()


async def get_article_by_id(session: AsyncSession, *, article_id: str) -> Article | None:
    result = await session.execute(select(Article).where(Article.id == article_id))
    return result.scalar_one_or_none()


async def delete_article(session: AsyncSession, article: Article) -> None:
    await session.delete(article)
    await session.flush()
