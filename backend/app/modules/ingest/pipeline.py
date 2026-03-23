"""Ingest pipeline 编排 — 串联 Phase 1→4。"""

from __future__ import annotations

import hashlib
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.types import (
    DocRoute,
    FetchedContent,
    IngestInput,
    IngestResult,
    InputType,
    TikaMetadata,
)

logger = structlog.get_logger(__name__)


async def run_pipeline(
    db: AsyncSession,
    *,
    ingest_input: IngestInput,
    article_id: str | None = None,
    existing_dedupe_keys: set[str] | None = None,
    mineru_batch_id: str | None = None,
    mineru_data_id: str | None = None,
    user=None,
) -> IngestResult:
    timings: dict[str, float] = {}
    pipeline_start = perf_counter()

    # ========== phase 1 接入层：拉取 + Tika 检测 + 路由 ==========
    t0 = perf_counter()
    content = await _phase1_fetch_and_detect(ingest_input, skip_fetch=bool(mineru_batch_id))
    timings["fetch_detect"] = _ms(t0)

    # ====== 去重检查 ======
    if content.content_hash and existing_dedupe_keys and content.content_hash in existing_dedupe_keys:
        return IngestResult(
            is_duplicate=True,
            content_hash=content.content_hash,
            tika_mime=content.tika.mime_type,
            elapsed_stages=timings,
        )

    # ========== phase 2 解析层：MinerU / 直通 → raw markdown ==========
    from app.modules.ingest.parse import parse_to_markdown

    t0 = perf_counter()
    raw_markdown = await parse_to_markdown(
        content,
        mineru_batch_id=mineru_batch_id,
        mineru_data_id=mineru_data_id,
    )
    timings["parse"] = _ms(t0)

    if not raw_markdown:
        logger.warning("pipeline.parse_empty", route=content.route.value)
        return IngestResult(
            tika_mime=content.tika.mime_type,
            content_hash=content.content_hash or "",
            elapsed_stages=timings,
        )

    # ========== phase 3 规范化 + 渲染：remark ==========
    from app.modules.ingest.normalize import process_markdown

    t0 = perf_counter()
    remark = await process_markdown(raw_markdown)
    timings["normalize"] = _ms(t0)

    # ====== 增强：summary + TOC fallback ======
    from app.modules.ingest.enhance import enhance

    t0 = perf_counter()
    title = ingest_input.title or content.tika.title or ""
    await enhance(
        db,
        remark=remark,
        article_id=article_id or "",
        title=title,
        language=content.tika.language or ingest_input.description,
        user=user,
    )
    timings["enhance"] = _ms(t0)

    # ========== phase 4 索引层：分块 + 向量化 ==========
    from app.modules.ingest.index import build_chunks, embed_chunks

    t0 = perf_counter()
    chunks = build_chunks(remark.clean_markdown)
    chunks = await embed_chunks(chunks)
    timings["index"] = _ms(t0)

    total_ms = _ms(pipeline_start)
    logger.info(
        "pipeline.complete",
        total_ms=total_ms,
        chunks=len(chunks),
        toc=len(remark.toc),
        fixes=remark.fixes_applied,
    )

    return IngestResult(
        clean_markdown=remark.clean_markdown,
        content_html=remark.html,
        mdast_json=remark.mdast,
        toc=remark.toc,
        chunks=chunks,
        title=title or None,
        author=ingest_input.author or content.tika.author,
        published_at=ingest_input.published_at,
        language=content.tika.language,
        reading_time_minutes=remark.reading_time_minutes,
        parser_name=f"mineru_cloud:{content.route.value}" if content.route.value != "text" else "text_passthrough",
        content_hash=hashlib.sha256(remark.clean_markdown.encode("utf-8")).hexdigest(),
        tika_mime=content.tika.mime_type,
        elapsed_stages=timings,
    )


async def _phase1_fetch_and_detect(inp: IngestInput, *, skip_fetch: bool = False) -> FetchedContent:
    """拉取 + 检测。

    skip_fetch=True: search import 已预提交 batch，不需要下载内容，
    构造空 FetchedContent 让 parse 阶段直接 poll batch。
    """
    is_url_source = inp.input_type in {InputType.URL, InputType.SEARCH_RESULT}

    # 预提交 batch 的 URL 来源跳过 fetch
    if skip_fetch and is_url_source:
        return FetchedContent(
            raw_bytes=b"",
            content_hash="",
            tika=TikaMetadata(),
            route=DocRoute.HTML,
            source_url=inp.source_url,
            file_name=None,
        )

    from app.modules.ingest.fetch import fetch_content
    from app.modules.ingest.detect import detect_and_route

    try:
        raw_bytes, file_name = await fetch_content(inp)
    except Exception as exc:
        if is_url_source and inp.source_url:
            logger.warning("pipeline.fetch_failed_url_fallback", url=inp.source_url, error=str(exc)[:200])
            return FetchedContent(
                raw_bytes=b"",
                content_hash="",
                tika=TikaMetadata(),
                route=DocRoute.HTML,
                source_url=inp.source_url,
                file_name=None,
            )
        raise

    return await detect_and_route(
        raw_bytes,
        file_name=file_name,
        source_url=inp.source_url,
    )


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
