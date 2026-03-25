"""Ingest service — 对外唯一入口。

调用 pipeline 并返回结果，调用方负责持久化。
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.pipeline import run_pipeline
from app.modules.ingest.types import IngestInput, IngestResult

logger = structlog.get_logger(__name__)


async def ingest(
    db: AsyncSession,
    *,
    ingest_input: IngestInput,
    article_id: str | None = None,
    existing_dedupe_keys: set[str] | None = None,
    mineru_batch_id: str | None = None,
    mineru_data_id: str | None = None,
    user=None,
) -> IngestResult:
    result = await run_pipeline(
        db,
        ingest_input=ingest_input,
        article_id=article_id,
        existing_dedupe_keys=existing_dedupe_keys,
        mineru_batch_id=mineru_batch_id,
        mineru_data_id=mineru_data_id,
        user=user,
    )

    if result.is_duplicate:
        logger.info("ingest.skipped_duplicate", hash=result.content_hash)
        return result

    if result.clean_markdown is None:
        logger.warning("ingest.no_content")
        return result

    logger.info(
        "ingest.complete",
        title=result.title,
        parser=result.parser_name,
        chunks=len(result.chunks),
        toc=len(result.toc),
    )
    return result


def build_article_fields(result: IngestResult) -> dict:
    """从 pipeline 结果构建 Article 字段 dict，供调用方 setattr。"""

    if result.clean_markdown is None:
        return {"parse_status": "failed"}

    toc_json = [
        {"id": n.id, "title": n.title, "level": n.level, "anchor": n.anchor}
        for n in result.toc
    ]

    return {
        "title": result.title,
        "author": result.author,
        "published_at": result.published_at,
        "language": result.language,
        "clean_markdown": result.clean_markdown,
        "content_html": result.content_html,
        "mdast_json": result.mdast_json,
        "toc_json": toc_json,
        "content_hash": result.content_hash,
        "tika_mime": result.tika_mime,
        "reading_time_minutes": result.reading_time_minutes,
        "parser_name": result.parser_name,
        "article_retrieval_text": _build_retrieval_text(result),
        "parse_status": "ready",
        "parse_error_tag": None,
        "parse_error_message": None,
        "ingested_at": datetime.now(UTC),
    }


def build_article_chunk_rows(result: IngestResult) -> list[dict]:
    if not result.chunks:
        return []
    toc_title_by_id = {n.id: n.title for n in result.toc}
    return [
        {
            "chunk_index": c.chunk_index,
            "section_path": c.section_id,
            "heading_title": c.heading_title or toc_title_by_id.get(c.section_id or ""),
            "token_count": c.token_count,
            "chunk_text": c.text,
            "contextualized_text": c.contextualized_text,
            "chunk_vector": c.embedding,
            "created_at": datetime.now(UTC),
        }
        for c in result.chunks
    ]


def _build_retrieval_text(result: IngestResult) -> str:
    if result.chunks:
        return "\n\n".join(c.text for c in result.chunks[:8])
    return (result.clean_markdown or "")[:4000]
