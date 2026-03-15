"""Ingest service – the single entry point for content ingestion.

Creates an Article, runs the ADR-002 pipeline, and persists the
results (clean_markdown, toc, chunks) back to the database.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.pipeline import run_pipeline
from app.modules.ingest.pipeline.observer import IngestPipelineObserver
from app.modules.ingest.pipeline.types import ChunkDraft, IngestContext, IngestInput, IngestResult

logger = structlog.get_logger(__name__)


async def ingest(
    db: AsyncSession,
    *,
    ingest_input: IngestInput,
    existing_dedupe_keys: set[str] | None = None,
    exa_api_key: str | None = None,
) -> IngestResult:
    """Run the full ingest pipeline and persist results.

    This is the **only** public function external modules need to call.
    """

    observer = IngestPipelineObserver(input_type=ingest_input.input_type.value)
    ctx = IngestContext(
        ingest_input=ingest_input,
        existing_dedupe_keys=existing_dedupe_keys or set(),
        exa_api_key=exa_api_key,
    )

    result = await run_pipeline(ctx, observer=observer)

    if result.is_duplicate:
        logger.info(
            "ingest.skipped_duplicate",
            dedupe_article_id=result.duplicate_article_id,
        )
        return result

    if result.fused_doc is None:
        logger.warning("ingest.no_fused_doc")
        return result

    # Persist results to the Article and ArticleChunk tables.
    # The actual ORM writes are deferred to the caller who owns the
    # db session and Article lifecycle.  We return the IngestResult
    # with all data ready for persistence.
    logger.info(
        "ingest.complete",
        title=result.fused_doc.title,
        quality_score=result.quality_score,
        primary_parser=result.primary_parser,
        chunk_count=len(result.chunks),
        toc_count=len(result.toc),
    )

    return result


def build_article_fields(result: IngestResult) -> dict:
    """Build a dict of Article column values from the pipeline result.

    The caller applies these to an Article ORM instance and commits.
    Includes block_graph_json and quality_profile_json so downstream
    pipelines (summary, chat) can consume them in separate requests.
    """

    if result.fused_doc is None:
        return {"parse_status": "failed"}

    toc_json = [
        {
            "id": n.id,
            "title": n.title,
            "level": n.level,
            "anchor": n.anchor,
            "is_synthetic": n.is_synthetic,
        }
        for n in result.toc
    ]

    block_graph_json = None
    if result.block_graph is not None:
        block_graph_json = {
            "blocks": [
                {
                    "block_id": b.block_id,
                    "block_type": b.block_type.value,
                    "text": b.text,
                    "section_id": b.section_id,
                    "anchor": f"L{b.line_start}",
                    "source_span": {
                        "lineStart": b.line_start,
                        "lineEnd": b.line_end,
                    },
                    "level": b.level,
                    "line_start": b.line_start,
                    "line_end": b.line_end,
                    "confidence": b.confidence,
                    "metadata": b.metadata,
                }
                for b in result.block_graph.blocks
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "relation": e.relation,
                }
                for e in result.block_graph.edges
            ],
        }

    quality_profile_json = None
    if result.quality_score > 0:
        quality_profile_json = {
            "total_score": result.quality_score,
            "primary_parser": result.primary_parser,
            "parse_candidate_count": result.parse_candidate_count,
            "doc_category": result.doc_route.category.value if result.doc_route else None,
            "toc_count": len(result.toc),
            "chunk_count": len(result.chunks),
            "block_count": len(result.block_graph.blocks) if result.block_graph else 0,
            "block_type_counts": result.block_graph.block_type_counts if result.block_graph else {},
        }

    clean_markdown = result.fused_doc.clean_markdown
    return {
        "title": result.fused_doc.title or None,
        "author": result.fused_doc.author,
        "published_at": result.fused_doc.published_at,
        "language": result.fused_doc.language,
        "clean_markdown": clean_markdown,
        "toc_json": toc_json,
        "block_graph_json": block_graph_json,
        "quality_profile_json": quality_profile_json,
        "content_hash": hashlib.sha256(clean_markdown.encode("utf-8")).hexdigest(),
        "parse_quality_score": result.fused_doc.quality_score,
        "parser_name": result.fused_doc.primary_parser,
        "article_retrieval_text": _build_article_retrieval_text(result),
        "parse_status": "ready",
        "parse_error_tag": None,
        "parse_error_message": None,
        "ingested_at": datetime.now(UTC),
    }


def build_article_chunk_rows(result: IngestResult) -> list[dict]:
    """Build ``ArticleChunk`` row payloads from pipeline chunks."""

    if not result.chunks:
        return []

    toc_title_by_id = {node.id: node.title for node in result.toc}
    return [
        _build_chunk_row(chunk, toc_title_by_id=toc_title_by_id)
        for chunk in result.chunks
    ]


def _build_chunk_row(
    chunk: ChunkDraft,
    *,
    toc_title_by_id: dict[str, str],
) -> dict:
    return {
        "chunk_index": chunk.chunk_index,
        "section_path": chunk.section_id,
        "heading_title": toc_title_by_id.get(chunk.section_id or ""),
        "token_count": chunk.token_count,
        "chunk_text": chunk.text,
        "chunk_vector": chunk.embedding,
        "created_at": datetime.now(UTC),
    }


def _build_article_retrieval_text(result: IngestResult) -> str:
    if result.chunks:
        return "\n\n".join(chunk.text for chunk in result.chunks[:8])
    return (result.fused_doc.clean_markdown or "")[:4000]
