from __future__ import annotations

from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.embedder import Embedder
from app.infra.telemetry.metrics import observe_ingest_chunks
from app.modules.ingest.indexing.chunker import chunk_markdown
from app.modules.ingest.indexing.indexer import replace_article_chunks
from app.modules.notebooks.models import Article

logger = structlog.get_logger(__name__)


async def index_article_content(
    session: AsyncSession,
    article: Article,
    *,
    user,
) -> dict[str, float | int | str]:
    if not article.clean_markdown:
        return {
            "chunk_count": 0,
            "chunking_ms": 0.0,
            "embedding_ms": 0.0,
            "persist_ms": 0.0,
            "index_total_ms": 0.0,
            "embedding_status": "skipped_no_content",
        }

    total_started = perf_counter()
    chunk_started = perf_counter()
    chunks = chunk_markdown(article.clean_markdown, toc=article.toc_json)
    chunking_ms = round((perf_counter() - chunk_started) * 1000, 2)
    article.chunk_status = "ready" if chunks else "not_started"
    article.index_status = "ready"
    article.embedding_provider = None
    article.embedding_model = None
    article.embedding_profile_key = None
    article.embedding_dimension = None

    embedder = Embedder.from_user(user)
    article_vector = None
    chunk_vectors = None
    embedding_ms = 0.0
    embedding_status = "skipped_unconfigured"
    if embedder.is_configured:
        embedding_started = perf_counter()
        try:
            texts = [article.article_retrieval_text or article.title, *[chunk.chunk_text for chunk in chunks]]
            embeddings = await embedder.embed_texts(texts)
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
            if embeddings:
                article_vector = embeddings[0]
                chunk_vectors = embeddings[1:]
                article.embedding_provider = embedder.provider
                article.embedding_model = embedder.model_name
                article.embedding_profile_key = embedder.profile_key
                article.embedding_dimension = len(article_vector)
                embedding_status = "generated"
            else:
                embedding_status = "empty"
        except Exception as exc:
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
            embedding_status = "failed"
            logger.exception(
                "ingest.embedding_failed",
                article_id=article.id,
                error=str(exc),
                embedding_ms=embedding_ms,
            )

    article.article_vector = article_vector
    observe_ingest_chunks(input_type=article.input_type, chunk_count=len(chunks))
    persist_started = perf_counter()
    await replace_article_chunks(
        session,
        article=article,
        chunks=chunks,
        vectors=chunk_vectors,
    )
    persist_ms = round((perf_counter() - persist_started) * 1000, 2)
    total_ms = round((perf_counter() - total_started) * 1000, 2)
    stats = {
        "chunk_count": len(chunks),
        "chunking_ms": chunking_ms,
        "embedding_ms": embedding_ms,
        "persist_ms": persist_ms,
        "index_total_ms": total_ms,
        "embedding_status": embedding_status,
    }
    logger.info(
        "ingest.index_completed",
        article_id=article.id,
        notebook_id=article.notebook_id,
        input_type=article.input_type,
        provider=article.embedding_provider or embedder.provider,
        model=article.embedding_model or embedder.model_name,
        **stats,
    )
    return stats
