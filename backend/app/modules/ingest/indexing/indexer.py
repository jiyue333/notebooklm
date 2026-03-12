from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.indexing.chunker import ChunkDraft
from app.modules.notebooks.models import Article, ArticleChunk


async def replace_article_chunks(
    session: AsyncSession,
    *,
    article: Article,
    chunks: list[ChunkDraft],
    vectors: list[list[float]] | None = None,
) -> None:
    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article.id))
    created_at = datetime.now(UTC)
    for chunk in chunks:
        vector = None
        if vectors is not None and chunk.chunk_index < len(vectors):
            vector = vectors[chunk.chunk_index]
        session.add(
            ArticleChunk(
                article_id=article.id,
                chunk_index=chunk.chunk_index,
                section_path=chunk.section_path,
                heading_title=chunk.heading_title,
                token_count=chunk.token_count,
                chunk_text=chunk.chunk_text,
                chunk_vector=vector,
                created_at=created_at,
            )
        )
