"""Sparse retrieval — PostgreSQL tsvector BM25。"""

from __future__ import annotations

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.retrieval.types import RetrievalResult
from app.modules.notebooks.models import Article, ArticleChunk

logger = structlog.get_logger(__name__)


async def sparse_retrieval(
    db: AsyncSession,
    *,
    query: str,
    scope_article_ids: list[str],
    top_k: int = 15,
) -> list[RetrievalResult]:
    """基于 chunk_tsv 的 BM25 全文检索。"""

    if not scope_article_ids or not query.strip():
        return []

    tsquery = func.plainto_tsquery("simple", query)

    stmt = (
        select(
            ArticleChunk.id,
            ArticleChunk.article_id,
            ArticleChunk.chunk_index,
            ArticleChunk.chunk_text,
            ArticleChunk.contextualized_text,
            ArticleChunk.section_path,
            ArticleChunk.heading_title,
            func.ts_rank_cd(ArticleChunk.chunk_tsv, tsquery).label("rank"),
        )
        .where(
            ArticleChunk.article_id.in_(scope_article_ids),
            ArticleChunk.chunk_tsv.op("@@")(tsquery),
        )
        .order_by(func.ts_rank_cd(ArticleChunk.chunk_tsv, tsquery).desc())
        .limit(top_k)
    )

    result = await db.execute(stmt)
    rows = result.all()

    article_titles = await _load_article_titles(db, scope_article_ids)

    return [
        RetrievalResult(
            chunk_id=row.id,
            article_id=row.article_id,
            article_title=article_titles.get(row.article_id, ""),
            chunk_index=row.chunk_index,
            raw_text=row.chunk_text,
            contextualized_text=row.contextualized_text or row.chunk_text,
            locator_text=_build_locator_text(row.chunk_text),
            score=float(row.rank),
            sparse_score=float(row.rank),
            section_path=row.section_path,
            heading_title=row.heading_title,
        )
        for row in rows
    ]


async def _load_article_titles(
    db: AsyncSession,
    article_ids: list[str],
) -> dict[str, str]:
    if not article_ids:
        return {}
    result = await db.execute(
        select(Article.id, Article.title).where(Article.id.in_(article_ids))
    )
    return {row.id: row.title for row in result.all()}


def _build_locator_text(raw_text: str) -> str:
    text = str(raw_text or "")
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace("`", "")
    text = text.replace("#", " ")
    text = text.replace("*", " ")
    text = text.replace("_", " ")
    text = text.replace("[", " ").replace("]", " ")
    text = text.replace("(", " ").replace(")", " ")
    text = " ".join(text.split())
    return text[:240]
