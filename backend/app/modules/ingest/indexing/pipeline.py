from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.embedder import Embedder
from app.infra.telemetry.tracing import start_span
from app.modules.ingest.indexing.chunker import chunk_markdown
from app.modules.ingest.indexing.indexer import replace_article_chunks
from app.modules.notebooks.models import Article
from app.modules.tracker.document_types import classify_document_type
from app.modules.tracker import IngestTracker

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

    tracker = IngestTracker(
        input_type=article.input_type,
        document_type=classify_document_type(
            input_type=article.input_type,
            file_name=article.file_name,
            file_mime=article.file_mime,
            parser_name=article.parser_name,
            markdown=article.clean_markdown,
        ),
    )

    with tracker.stage("chunk", span_attrs={"article_id": article.id}):
        chunks = chunk_markdown(article.clean_markdown, toc=article.toc_json)

    article.chunk_status = "ready" if chunks else "not_started"
    article.index_status = "ready"
    article.embedding_provider = None
    article.embedding_model = None
    article.embedding_profile_key = None
    article.embedding_dimension = None

    embedder = Embedder.from_user(user)
    article_vector = None
    chunk_vectors = None
    embedding_status = "skipped_unconfigured"
    if embedder.is_configured:
        with tracker.stage(
            "embed",
            span_attrs={
                "embedding_provider": embedder.provider,
                "embedding_model": embedder.model_name,
            },
        ) as ctx:
            try:
                texts = [article.article_retrieval_text or article.title, *[chunk.chunk_text for chunk in chunks]]
                embeddings = await embedder.embed_texts(texts)
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
                ctx.status = "error"
                embedding_status = "failed"
                logger.exception(
                    "ingest.embedding_failed",
                    article_id=article.id,
                    error=str(exc),
                )
    else:
        tracker.report_stage_manual("embed", "skipped", 0.0)

    article.article_vector = article_vector
    tracker.report_chunks(len(chunks))

    with tracker.stage("persist", span_attrs={"chunk_count": len(chunks)}):
        await replace_article_chunks(
            session,
            article=article,
            chunks=chunks,
            vectors=chunk_vectors,
        )

    with tracker.stage("index_total") as ctx:
        # index_total 仅记录总耗时，不执行额外操作
        pass
    # 用 stage timings 中已有的各阶段时间覆盖 index_total 的值
    total_ms = sum(tracker.timings.get(s, 0.0) for s in ("chunk", "embed", "persist"))
    tracker.timings["index_total"] = total_ms

    stats = {
        "chunk_count": len(chunks),
        "chunking_ms": tracker.timings.get("chunk", 0.0),
        "embedding_ms": tracker.timings.get("embed", 0.0),
        "persist_ms": tracker.timings.get("persist", 0.0),
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
