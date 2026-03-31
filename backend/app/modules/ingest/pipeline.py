"""Ingest pipeline 编排 — 串联 Phase 1→4。"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
from collections import Counter
from time import perf_counter
from typing import Any

import httpx
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
from app.modules.ingest.contextualize import contextualize_chunks
from app.modules.ingest.detect import detect_and_route
from app.modules.ingest.enhance import ensure_toc, warm_summary
from app.modules.ingest.errors import IngestPipelineError
from app.modules.ingest.fetch import fetch_content
from app.modules.ingest.index import build_chunks, embed_chunks
from app.modules.ingest.normalize import process_markdown
from app.modules.ingest.parse import parse_to_markdown
from app.modules.ingest.types import (
    DocRoute,
    FetchedContent,
    IngestInput,
    IngestResult,
    InputType,
    TikaMetadata,
)

logger = structlog.get_logger(__name__)

_MARKDOWN_STRUCT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),             # heading
    re.compile(r"(?m)^\s{0,3}(?:[-*+]\s+\S|\d+\.\s+\S)"),  # list
    re.compile(r"(?m)^\s{0,3}>\s+\S"),                  # blockquote
    re.compile(r"(?m)^\s{0,3}```"),                     # fenced code
    re.compile(r"(?m)^\s{0,3}(?:---|\*\*\*|___)\s*$"),  # hr
    re.compile(r"(?m)^\s*\|.+\|\s*$"),                  # table row
)
_MARKDOWN_INLINE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\[[^\]]+\]\([^)]+\)"),                 # link
    re.compile(r"!\[[^\]]*]\([^)]+\)"),                 # image
    re.compile(r"(^|[\s(])\*\*[^*]+\*\*"),              # bold
    re.compile(r"(^|[\s(])`[^`]+`"),                    # inline code
)
_HTML_TAG_PATTERN = re.compile(r"</?[a-zA-Z][^>\n]{0,120}>")


def _eval_force_serial_enabled() -> bool:
    value = str(os.getenv("EVAL_FORCE_SERIAL") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


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


def _looks_like_markdown_text(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False

    if any(pattern.search(text) for pattern in _MARKDOWN_STRUCT_PATTERNS):
        return True

    inline_hits = sum(1 for pattern in _MARKDOWN_INLINE_PATTERNS if pattern.search(text))
    if inline_hits >= 2:
        return True
    if inline_hits == 1 and len(text.splitlines()) >= 3:
        return True

    if _HTML_TAG_PATTERN.search(text):
        return False

    return False


async def run_pipeline(
    db: AsyncSession,
    *,
    ingest_input: IngestInput,
    article_id: str | None = None,
    existing_dedupe_keys: set[str] | None = None,
    mineru_batch_id: str | None = None,
    mineru_data_id: str | None = None,
    notebook_title: str = "",
    user=None,
) -> IngestResult:
    timings: dict[str, float] = {}
    pipeline_start = perf_counter()
    input_type = ingest_input.input_type.value
    # 持有后台 summary task 的引用，防止 asyncio 提前 GC
    _background_tasks: set[asyncio.Task] = set()

    # ========== phase 1 接入层：拉取 + Tika 检测 + 路由 ==========
    t0 = perf_counter()
    try:
        content, phase1_ms, fetch_url_fallback = await _phase1_fetch_and_detect(
            ingest_input, skip_fetch=bool(mineru_batch_id)
        )
    except IngestPipelineError as exc:
        timings["fetch_detect"] = _ms(t0)
        observe_ingest_stage(
            stage="fetch_detect",
            input_type=input_type,
            status="failed",
            duration_ms=timings["fetch_detect"],
        )
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
        return _failed_result(
            content_hash="",
            tika_mime=None,
            elapsed_stages=timings,
            tag=exc.tag,
            message=exc.message,
        )
    except Exception as exc:
        timings["fetch_detect"] = _ms(t0)
        observe_ingest_stage(
            stage="fetch_detect",
            input_type=input_type,
            status="failed",
            duration_ms=timings["fetch_detect"],
        )
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
        return _failed_result(
            content_hash="",
            tika_mime=None,
            elapsed_stages=timings,
            tag="fetch_failed",
            message=str(exc)[:500] or "获取来源失败",
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
    logger.debug(
        "pipeline.fetch_detect_ok",
        route=content.route.value,
        mime=content.tika.mime_type,
        content_bytes=len(content.raw_bytes),
        content_hash=content.content_hash[:12] if content.content_hash else None,
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
    t0 = perf_counter()
    try:
        raw_markdown = await parse_to_markdown(
            content,
            mineru_batch_id=mineru_batch_id,
            mineru_data_id=mineru_data_id,
        )
    except Exception as exc:
        timings["parse"] = _ms(t0)
        observe_ingest_stage(
            stage="parse",
            input_type=input_type,
            status="failed",
            duration_ms=timings["parse"],
        )
        observe_ingest_parse_success(input_type=input_type, parser=content.route.value, result="failed")
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
        return _failed_result(
            content_hash=content.content_hash,
            tika_mime=content.tika.mime_type,
            elapsed_stages=timings,
            tag="parse_failed",
            message=str(exc)[:500] or "文档解析失败",
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
        return _failed_result(
            content_hash=content.content_hash or "",
            tika_mime=content.tika.mime_type,
            elapsed_stages=timings,
            tag="parse_empty",
            message="解析未生成可用正文",
        )

    # ========== phase 3 规范化 + 渲染：remark ==========
    t0 = perf_counter()
    try:
        remark = await process_markdown(raw_markdown)
    except Exception as exc:
        timings["normalize"] = _ms(t0)
        observe_ingest_stage(
            stage="normalize",
            input_type=input_type,
            status="failed",
            duration_ms=timings["normalize"],
        )
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
        return _failed_result(
            content_hash=content.content_hash or "",
            tika_mime=content.tika.mime_type,
            elapsed_stages=timings,
            tag="normalize_failed",
            message=str(exc)[:500] or "正文规范化失败",
        )
    timings["normalize"] = _ms(t0)

    title = ingest_input.title or content.tika.title or ""
    # ====== 增强：优先补 TOC，随后 summary 与 index 并行 ======
    toc_t0 = perf_counter()
    try:
        await ensure_toc(
            remark=remark,
            title=title,
            language=content.tika.language or None,
        )
    except Exception as exc:
        logger.warning("pipeline.ensure_toc_failed", error=str(exc)[:200])
    timings["enhance_toc"] = _ms(toc_t0)

    summary_t0 = perf_counter()
    summary_task: asyncio.Task[Any] | None = None
    if not _eval_force_serial_enabled():
        summary_task = asyncio.create_task(
            warm_summary(
                db,
                remark=remark,
                article_id=article_id or "",
                title=title,
                language=content.tika.language or None,
                user=user,
            )
        )
        # 防止 GC 在 await 之前把 task 回收
        _background_tasks.add(summary_task)
        summary_task.add_done_callback(_background_tasks.discard)

    # ========== phase 4 索引层：分块 + 上下文增强 + 向量化 ==========
    t0 = perf_counter()
    try:
        chunk_t0 = perf_counter()
        chunks = build_chunks(remark.clean_markdown, toc=remark.toc)
        timings["index_build_chunks"] = _ms(chunk_t0)
        logger.debug(
            "pipeline.index_build_chunks",
            chunk_count=len(chunks),
            duration_ms=timings["index_build_chunks"],
        )

        ctx_t0 = perf_counter()
        chunks = await contextualize_chunks(
            chunks,
            notebook_title=notebook_title,
            article_title=title,
            toc=remark.toc,
            clean_markdown=remark.clean_markdown,
        )
        timings["index_contextualize"] = _ms(ctx_t0)
        logger.debug(
            "pipeline.index_contextualize",
            chunk_count=len(chunks),
            duration_ms=timings["index_contextualize"],
        )

        embed_t0 = perf_counter()
        chunks = await embed_chunks(chunks, user=user)
        timings["index_embed"] = _ms(embed_t0)
        logger.debug(
            "pipeline.index_embed",
            chunk_count=len(chunks),
            has_vectors=any(c.embedding for c in chunks),
            duration_ms=timings["index_embed"],
        )
    except Exception as exc:
        timings["index"] = _ms(t0)
        observe_ingest_stage(
            stage="index",
            input_type=input_type,
            status="failed",
            duration_ms=timings["index"],
        )
        if summary_task is not None:
            summary_task.cancel()
        else:
            # eval 串行模式：异常路径也跳过 summary warm
            pass
        observe_ingest_e2e(input_type=input_type, duration_ms=_ms(pipeline_start))
        return _failed_result(
            content_hash=content.content_hash or "",
            tika_mime=content.tika.mime_type,
            elapsed_stages=timings,
            tag="index_failed",
            message=str(exc)[:500] or "索引阶段失败",
        )
    timings["index"] = _ms(t0)
    # summary_task 已在后台运行，不阻塞关键路径
    # eval 串行模式下没有 task，直接内联执行一次（便于测试）
    if _eval_force_serial_enabled():
        await warm_summary(
            db,
            remark=remark,
            article_id=article_id or "",
            title=title,
            language=content.tika.language or None,
            user=user,
        )
    timings["enhance"] = _ms(summary_t0)

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
        # ── 各阶段耗时明细 ──────────────────────────────────────────
        t_fetch_detect_ms=timings.get("fetch_detect"),
        t_parse_ms=timings.get("parse"),
        t_normalize_ms=timings.get("normalize"),
        t_enhance_toc_ms=timings.get("enhance_toc"),
        t_index_build_ms=timings.get("index_build_chunks"),
        t_index_ctx_ms=timings.get("index_contextualize"),
        t_index_embed_ms=timings.get("index_embed"),
        t_index_total_ms=timings.get("index"),
        t_summary_warm_ms=timings.get("enhance"),
        # ── 内容元数据 ───────────────────────────────────────────────
        route=content.route.value,
        content_bytes=len(content.raw_bytes),
        markdown_chars=len(remark.clean_markdown),
        parser=parser_name,
    )

    # ── 慢阶段检测：超过阈值时打 warning 便于 grep ──────────────────
    _SLOW_THRESHOLDS_MS: dict[str, float] = {
        "fetch_detect": 5_000,
        "parse": 60_000,
        "normalize": 3_000,
        "enhance_toc": 5_000,
        "index_build_chunks": 1_000,
        "index_contextualize": 10_000,
        "index_embed": 15_000,
        "enhance": 35_000,
    }
    slow_stages = {
        k: v for k, v in timings.items() if v > _SLOW_THRESHOLDS_MS.get(k, float("inf"))
    }
    if slow_stages:
        logger.warning(
            "pipeline.slow_stages_detected",
            slow_stages=slow_stages,
            total_ms=total_ms,
            route=content.route.value,
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
        remark_fixes_applied=remark.fixes_applied,
    )


async def _phase1_fetch_and_detect(
    inp: IngestInput, *, skip_fetch: bool = False
) -> tuple[FetchedContent, dict[str, float], bool]:
    """拉取 + 检测。返回 (内容, {fetch_ms, detect_ms}, 是否 URL fetch 失败降级)。"""

    is_url_source = inp.input_type in {InputType.URL, InputType.SEARCH_RESULT}

    # TEXT 输入（手动粘贴）：一律 TEXT 直通，parse 阶段原样 UTF-8 解码。
    # 粘贴语义本身就是可读正文，不需要按 Markdown 特征改走 MinerU 解析。
    if inp.input_type == InputType.TEXT:
        fetch_t0 = perf_counter()
        raw_bytes, file_name = await fetch_content(inp)
        fetch_ms = _ms(fetch_t0)
        detect_t0 = perf_counter()
        raw_text = raw_bytes.decode("utf-8", errors="replace")
        is_markdown = _looks_like_markdown_text(raw_text)
        route = DocRoute.TEXT
        tika_mime = "text/markdown"
        detect_ms = _ms(detect_t0)
        resolved_file_name = file_name or "input.md"
        content = FetchedContent(
            raw_bytes=raw_bytes,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            tika=TikaMetadata(mime_type=tika_mime),
            route=route,
            source_url=inp.source_url,
            file_name=resolved_file_name,
        )
        logger.debug(
            "pipeline.text_route_decision",
            is_markdown=is_markdown,
            route=route.value,
            text_length=len(raw_text),
        )
        return content, {"fetch_ms": fetch_ms, "detect_ms": detect_ms}, False

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

    fetch_t0 = perf_counter()
    try:
        raw_bytes, file_name = await fetch_content(inp)
    except Exception as exc:
        if is_url_source and inp.source_url and _allow_url_fallback(exc):
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


def _allow_url_fallback(exc: Exception) -> bool:
    if isinstance(exc, IngestPipelineError):
        return False
    return isinstance(exc, httpx.HTTPError)


def _failed_result(
    *,
    content_hash: str,
    tika_mime: str | None,
    elapsed_stages: dict[str, float],
    tag: str,
    message: str,
) -> IngestResult:
    return IngestResult(
        clean_markdown=None,
        content_hash=content_hash,
        tika_mime=tika_mime,
        elapsed_stages=elapsed_stages,
        parse_error_tag=tag,
        parse_error_message=message[:500],
    )
