from __future__ import annotations

import re

from sqlalchemy import case, desc, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notebooks.models import Article
from app.modules.retrieval.fusion import rrf_fuse


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[\s,，。！？；:：/()（）]+", text.lower()) if len(token) >= 2]


async def retrieve_related_articles(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None = None,
    limit: int = 5,
) -> list[Article]:
    query_text = query.strip()
    if not query_text:
        return []

    lexical_ids = await _lexical_search(
        session,
        user_id=user_id,
        query=query_text,
        exclude_article_id=exclude_article_id,
        limit=max(limit * 3, 10),
    )
    title_ids = await _title_search(
        session,
        user_id=user_id,
        query=query_text,
        exclude_article_id=exclude_article_id,
        limit=max(limit * 3, 10),
    )
    fused_ids = rrf_fuse([lexical_ids, title_ids], limit=limit)
    if not fused_ids:
        return []

    result = await session.execute(
        select(Article).where(Article.id.in_(fused_ids))
    )
    article_map = {article.id: article for article in result.scalars().all()}
    return [article_map[item_id] for item_id in fused_ids if item_id in article_map]


async def _lexical_search(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None,
    limit: int,
) -> list[str]:
    ts_query = func.websearch_to_tsquery("simple", query)
    rank_expr = func.ts_rank_cd(Article.article_tsv, ts_query)
    stmt = (
        select(Article.id)
        .where(
            Article.user_id == user_id,
            Article.article_tsv.op("@@")(ts_query),
        )
        .order_by(desc(rank_expr), desc(Article.updated_at))
        .limit(limit)
    )
    if exclude_article_id:
        stmt = stmt.where(Article.id != exclude_article_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _title_search(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None,
    limit: int,
) -> list[str]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    score_expr = literal(0)
    filters = []
    for token in tokens:
        pattern = f"%{token}%"
        filters.append(Article.title.ilike(pattern))
        score_expr = score_expr + case((Article.title.ilike(pattern), 1), else_=0)

    stmt = (
        select(Article.id)
        .where(Article.user_id == user_id, or_(*filters))
        .order_by(desc(score_expr), desc(Article.updated_at))
        .limit(limit)
    )
    if exclude_article_id:
        stmt = stmt.where(Article.id != exclude_article_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())
