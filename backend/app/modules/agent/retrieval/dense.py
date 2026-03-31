"""Dense retrieval — pgvector cosine similarity。"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.embedder import Embedder
from app.modules.agent.retrieval.types import RetrievalResult
from app.modules.notebooks.models import Article, ArticleChunk

logger = structlog.get_logger(__name__)


async def dense_retrieval(
    db: AsyncSession,
    *,
    query_embedding: list[float],
    scope_article_ids: list[str],
    top_k: int = 15,
) -> list[RetrievalResult]:
    """基于 chunk_vector 的 cosine 相似度检索。"""

    if not scope_article_ids or not query_embedding:
        return []

    stmt = (
        select(
            ArticleChunk.id,
            ArticleChunk.article_id,
            ArticleChunk.chunk_index,
            ArticleChunk.chunk_text,
            ArticleChunk.contextualized_text,
            ArticleChunk.section_path,
            ArticleChunk.heading_title,
            ArticleChunk.chunk_vector.cosine_distance(query_embedding).label("distance"),
        )
        .where(
            ArticleChunk.article_id.in_(scope_article_ids),
            ArticleChunk.chunk_vector.isnot(None),
        )
        .order_by("distance")
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
            score=1.0 - row.distance,
            dense_score=1.0 - row.distance,
            section_path=row.section_path,
            heading_title=row.heading_title,
        )
        for row in rows
    ]


async def embed_query(query: str, *, user=None) -> list[float] | None:
    """对 query 文本做 embedding。"""
    try:
        from app.modules.settings.runtime import resolve_embedding_runtime_config

        runtime_config = resolve_embedding_runtime_config(user)
        embedder = Embedder(runtime_config)
        if not embedder.is_configured:
            return None
        vectors = await embedder.embed_texts([query])
        return vectors[0] if vectors else None
    except Exception as exc:
        logger.warning("dense.embed_query_failed", error=str(exc)[:200])
        return None


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
