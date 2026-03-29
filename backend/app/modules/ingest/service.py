"""Ingest service — 对外唯一入口。

调用 pipeline 并返回结果，调用方负责持久化。
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.errors import InvalidIngestInputError
from app.modules.ingest.pipeline import run_pipeline
from app.modules.ingest.types import IngestInput, IngestResult, InputType

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
    try:
        _validate_ingest_input(ingest_input)
    except InvalidIngestInputError as exc:
        logger.warning("ingest.invalid_input", tag=exc.tag, message=exc.message)
        return IngestResult(
            clean_markdown=None,
            parse_error_tag=exc.tag,
            parse_error_message=exc.message,
        )

    result = await run_pipeline(
        db,
        ingest_input=ingest_input,
        article_id=article_id,
        existing_dedupe_keys=existing_dedupe_keys,
        mineru_batch_id=mineru_batch_id,
        mineru_data_id=mineru_data_id,
        notebook_title=ingest_input.notebook_title,
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
        return {
            "parse_status": "failed",
            "parse_error_tag": result.parse_error_tag or "ingest_failed",
            "parse_error_message": result.parse_error_message or "解析链路失败，请稍后重试。",
        }

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


def _validate_ingest_input(ingest_input: IngestInput) -> None:
    if not (ingest_input.user_id or "").strip():
        raise InvalidIngestInputError("缺少 user_id，无法执行解析。")
    if not (ingest_input.notebook_id or "").strip():
        raise InvalidIngestInputError("缺少 notebook_id，无法执行解析。")

    if ingest_input.input_type == InputType.FILE:
        has_bytes = isinstance(ingest_input.file_bytes, (bytes, bytearray)) and bool(ingest_input.file_bytes)
        has_file_name = bool((ingest_input.file_name or "").strip())
        if not has_bytes and not has_file_name:
            raise InvalidIngestInputError("FILE 类型需要 file_bytes 或 file_name。")
        return

    if ingest_input.input_type in {InputType.URL, InputType.SEARCH_RESULT}:
        if not (ingest_input.source_url or "").strip():
            raise InvalidIngestInputError(f"{ingest_input.input_type.value} 类型需要 source_url。")
        return

    if ingest_input.input_type == InputType.TEXT:
        if not (ingest_input.raw_text or "").strip():
            raise InvalidIngestInputError("TEXT 类型需要非空 raw_text。")
