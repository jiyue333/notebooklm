from __future__ import annotations

from sqlalchemy import Select, asc, desc, or_, select
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
    tags: list[str] | None = None,
) -> Notebook:
    notebook = Notebook(user_id=user_id, title=title, emoji=emoji, color=color, tags_json=tags)
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
        .order_by(desc(Article.created_at), desc(Article.id))
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


async def get_notebook_by_title(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
) -> Notebook | None:
    result = await session.execute(
        _owned_notebook_query(user_id).where(Notebook.title.ilike(title.strip()))
    )
    return result.scalar_one_or_none()


async def mark_notebook_opened(
    session: AsyncSession,
    *,
    notebook: Notebook,
    opened_at,
) -> None:
    notebook.last_opened_at = opened_at
    await session.flush()


async def search_notebooks_and_articles(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    limit: int = 20,
) -> list[dict]:
    normalized = query.strip()
    if not normalized:
        return []

    notebook_rows = await session.execute(
        select(Notebook.id, Notebook.title, Notebook.tags_json)
        .where(Notebook.user_id == user_id)
        .where(Notebook.title.ilike(f"%{normalized}%"))
        .order_by(desc(Notebook.updated_at))
        .limit(limit)
    )

    article_rows = await session.execute(
        select(Article.notebook_id, Article.id, Article.title)
        .where(Article.user_id == user_id)
        .where(
            or_(
                Article.title.ilike(f"%{normalized}%"),
                Article.clean_markdown.ilike(f"%{normalized}%"),
                Article.preview_markdown.ilike(f"%{normalized}%"),
            )
        )
        .order_by(desc(Article.updated_at), desc(Article.created_at))
        .limit(limit)
    )

    notebook_hits = [
        {
            "type": "notebook",
            "notebookId": notebook_id,
            "title": title,
            "tags": tags or [],
        }
        for notebook_id, title, tags in notebook_rows.all()
    ]
    article_hits = [
        {
            "type": "article",
            "notebookId": notebook_id,
            "articleId": article_id,
            "title": title,
        }
        for notebook_id, article_id, title in article_rows.all()
    ]
    return notebook_hits + article_hits
