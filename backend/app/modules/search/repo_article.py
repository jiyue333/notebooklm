from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notebooks.models import Article


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


async def get_article_by_id(session: AsyncSession, *, article_id: str | None) -> Article | None:
    if not article_id:
        return None
    result = await session.execute(select(Article).where(Article.id == article_id))
    return result.scalar_one_or_none()


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
    counts = defaultdict(int)
    for notebook_id, count in result.all():
        counts[notebook_id] = count
    return dict(counts)


async def list_existing_dedupe_keys(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    dedupe_keys: list[str],
) -> set[str]:
    if not dedupe_keys:
        return set()
    result = await session.execute(
        select(Article.dedupe_key).where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
            Article.dedupe_key.in_(dedupe_keys),
        )
    )
    return set(result.scalars().all())


async def create_search_result_article(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
    search_result,
    created_at: datetime,
) -> Article:
    article = Article(
        user_id=user_id,
        notebook_id=notebook_id,
        input_type="search_result",
        origin_search_session_id=search_session_id,
        origin_search_result_id=search_result.id,
        source_url=search_result.raw_url,
        normalized_url=search_result.canonical_url,
        dedupe_key=search_result.url_hash,
        source_title_raw=search_result.title,
        title=search_result.title,
        author=search_result.author,
        published_at=search_result.published_at,
        preview_markdown=search_result.preview_markdown or search_result.description,
        parse_status="queued",
        chunk_status="not_started",
        index_status="not_started",
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(article)
    await session.flush()
    return article


async def create_article(session: AsyncSession, article: Article) -> Article:
    session.add(article)
    await session.flush()
    return article
