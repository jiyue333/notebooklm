"""Ingest pipeline 编排 — 串联 Phase 1→4。"""

from __future__ import annotations

import hashlib
from collections import Counter
from time import perf_counter
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.telemetry.metrics import (
    observe_ingest_block_completeness,
    observe_ingest_e2e,
    observe_ingest_fallback_rate,
    observe_ingest_fetch_latency,
    observe_ingest_parse_success,
    observe_ingest_route_distribution,
    observe_ingest_stage,
    observe_ingest_synthetic_toc,
)
from app.modules.ingest.types import (
    DocRoute,
    FetchedContent,
    IngestInput,
    IngestResult,
    InputType,
    TikaMetadata,
)

logger = structlog.get_logger(__name__)


def _mdast_type_counts(mdast: dict[str, Any] | None) -> Counter[str]:
    """统计 mdast 节点 type，用于 block 分布指标。"""

    counts: Counter[str] = Counter()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, str):
                counts[t] += 1
            for c in node.get("children") or ():
                walk(c)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    if mdast:
        walk(mdast)
    return counts


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
    input_type = ingest_input.input_type.value

    # ========== phase 1 接入层：拉取 + Tika 检测 + 路由 ==========
    t0 = perf_counter()
    content, phase1_ms, fetch_url_fallback = await _phase1_fetch_and_detect(
        ingest_input, skip_fetch=bool(mineru_batch_id)
    )
    timings["fetch_detect"] = _ms(t0)
    content_type_label = (content.tika.mime_type or "").strip() or content.route.value

    observe_ingest_fetch_latency(
        input_type=input_type,
        content_type=content_type_label,
        duration_ms=phase1_ms["fetch_ms"],
    )
    observe_ingest_route_distribution(input_type=input_type, category=content.route.value)
    observe_ingest_stage(
        stage="fetch_detect",
        input_type=input_type,
        status="ok",
        duration_ms=timings["fetch_detect"],
    )
    if fetch_url_fallback:
        observe_ingest_fallback_rate(input_type=input_type, trigger="fetch_url_empty")

    # ====== 去重检查 ======
    if content.content_hash and existing_dedupe_keys and content.content_hash in existing_dedupe_keys:
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
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
        observe_ingest_stage(
            stage="parse",
            input_type=input_type,
            status="empty",
            duration_ms=timings["parse"],
        )
        observe_ingest_parse_success(
            input_type=input_type,
            parser=content.route.value,
            result="empty",
        )
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
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
        language=content.tika.language or None,
        user=user,
    )
    timings["enhance"] = _ms(t0)

    # ========== phase 4 索引层：分块 + 上下文增强 + 向量化 ==========
    from app.modules.ingest.index import build_chunks, embed_chunks
    from app.modules.ingest.contextualize import contextualize_chunks

    t0 = perf_counter()
    chunks = build_chunks(remark.clean_markdown)
    # ====== step 1 notebook 标题需由调用方传入，pipeline 内无法获取 ======
    notebook_title = ""
    if hasattr(ingest_input, "_notebook_title"):
        notebook_title = ingest_input._notebook_title or ""
    chunks = await contextualize_chunks(
        chunks,
        notebook_title=notebook_title,
        article_title=title,
        toc=remark.toc,
        clean_markdown=remark.clean_markdown,
    )
    chunks = await embed_chunks(chunks)
    timings["index"] = _ms(t0)

    total_ms = _ms(pipeline_start)
    parser_name = (
        f"mineru_cloud:{content.route.value}" if content.route.value != "text" else "text_passthrough"
    )
    logger.info(
        "pipeline.complete",
        total_ms=total_ms,
        chunks=len(chunks),
        toc=len(remark.toc),
        fixes=remark.fixes_applied,
    )

    # ========== metrics ==========
    observe_ingest_stage(
        stage="parse",
        input_type=input_type,
        status="ok",
        duration_ms=timings["parse"],
    )
    observe_ingest_stage(
        stage="normalize",
        input_type=input_type,
        status="ok",
        duration_ms=timings["normalize"],
    )
    observe_ingest_stage(
        stage="enhance",
        input_type=input_type,
        status="ok",
        duration_ms=timings["enhance"],
    )
    observe_ingest_stage(
        stage="index",
        input_type=input_type,
        status="ok",
        duration_ms=timings["index"],
    )
    observe_ingest_parse_success(input_type=input_type, parser=parser_name, result="ok")
    observe_ingest_synthetic_toc(
        input_type=input_type,
        result="present" if remark.toc else "missing",
    )
    for btype, cnt in _mdast_type_counts(remark.mdast).items():
        observe_ingest_block_completeness(input_type=input_type, block_type=btype, count=cnt)
    observe_ingest_e2e(input_type=input_type, duration_ms=total_ms)

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
        parser_name=parser_name,
        content_hash=hashlib.sha256(remark.clean_markdown.encode("utf-8")).hexdigest(),
        tika_mime=content.tika.mime_type,
        elapsed_stages=timings,
    )


async def _phase1_fetch_and_detect(
    inp: IngestInput, *, skip_fetch: bool = False
) -> tuple[FetchedContent, dict[str, float], bool]:
    """拉取 + 检测。返回 (内容, {fetch_ms, detect_ms}, 是否 URL fetch 失败降级)。"""

    is_url_source = inp.input_type in {InputType.URL, InputType.SEARCH_RESULT}

    # 预提交 batch 的 URL 来源跳过 fetch
    if skip_fetch and is_url_source:
        return (
            FetchedContent(
                raw_bytes=b"",
                content_hash="",
                tika=TikaMetadata(),
                route=DocRoute.HTML,
                source_url=inp.source_url,
                file_name=None,
            ),
            {"fetch_ms": 0.0, "detect_ms": 0.0},
            False,
        )

    from app.modules.ingest.fetch import fetch_content
    from app.modules.ingest.detect import detect_and_route

    fetch_t0 = perf_counter()
    try:
        raw_bytes, file_name = await fetch_content(inp)
    except Exception as exc:
        if is_url_source and inp.source_url:
            logger.warning("pipeline.fetch_failed_url_fallback", url=inp.source_url, error=str(exc)[:200])
            return (
                FetchedContent(
                    raw_bytes=b"",
                    content_hash="",
                    tika=TikaMetadata(),
                    route=DocRoute.HTML,
                    source_url=inp.source_url,
                    file_name=None,
                ),
                {"fetch_ms": _ms(fetch_t0), "detect_ms": 0.0},
                True,
            )
        raise

    fetch_ms = _ms(fetch_t0)
    detect_t0 = perf_counter()
    content = await detect_and_route(
        raw_bytes,
        file_name=file_name,
        source_url=inp.source_url,
    )
    detect_ms = _ms(detect_t0)
    return content, {"fetch_ms": fetch_ms, "detect_ms": detect_ms}, False


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
