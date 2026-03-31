"""Phase 3a — 规范化层：通过 Node.js remark subprocess 处理 markdown。

输入 raw markdown → 输出 RemarkResult (AST + clean markdown + HTML + TOC + 阅读时间)。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from time import perf_counter

import structlog

from app.core.config import get_settings
from app.modules.ingest.types import RemarkResult, TOCNode

logger = structlog.get_logger(__name__)

_DEFAULT_SCRIPT = Path(__file__).resolve().parents[4] / "tools" / "remark-processor" / "index.mjs"
_WORKER_LOCK = asyncio.Lock()
_WORKER_PROC: asyncio.subprocess.Process | None = None
_WORKER_SCRIPT_PATH: str | None = None
_RESULT_CACHE: OrderedDict[str, RemarkResult] = OrderedDict()
_RESULT_CACHE_LOCK = asyncio.Lock()


_REMARK_SLOW_MS = 2_000  # remark 单次调用超过此值打 warning


async def process_markdown(raw_markdown: str) -> RemarkResult:
    """调用 Node.js remark-processor，返回规范化结果。"""

    cache_key = hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()
    cached = await _cache_get(cache_key)
    if cached:
        logger.debug(
            "normalize.cache_hit",
            key=cache_key[:16],
            input_chars=len(raw_markdown),
            output_chars=len(cached.clean_markdown),
        )
        return cached

    settings = get_settings()
    script_path = settings.remark_processor_path or str(_DEFAULT_SCRIPT)
    timeout = settings.remark_timeout_seconds
    cache_size = max(32, int(getattr(settings, "remark_cache_size", 256)))

    payload = json.dumps({"markdown": raw_markdown})
    t0 = perf_counter()
    data = await _invoke_remark_worker(payload=payload, script_path=script_path, timeout=timeout)
    remark_ms = round((perf_counter() - t0) * 1000, 2)

    if not data:
        logger.warning(
            "normalize.remark_no_data_fallback",
            input_chars=len(raw_markdown),
            duration_ms=remark_ms,
        )
        result = _fallback_result(raw_markdown)
        await _cache_set(cache_key, result, max_items=cache_size)
        return _clone_result(result)

    if data.get("error"):
        logger.warning(
            "normalize.remark_failed",
            stderr=str(data.get("error"))[:500],
            input_chars=len(raw_markdown),
            duration_ms=remark_ms,
        )
        result = _fallback_result(raw_markdown)
        await _cache_set(cache_key, result, max_items=cache_size)
        return _clone_result(result)

    try:
        result = _build_remark_result(data, raw_markdown=raw_markdown)
    except Exception as exc:
        logger.warning("normalize.remark_json_error", error=str(exc), duration_ms=remark_ms)
        result = _fallback_result(raw_markdown)
        await _cache_set(cache_key, result, max_items=cache_size)
        return _clone_result(result)

    log_fn = logger.warning if remark_ms > _REMARK_SLOW_MS else logger.debug
    log_fn(
        "normalize.remark_done",
        input_chars=len(raw_markdown),
        output_chars=len(result.clean_markdown),
        toc_count=len(result.toc),
        fixes=result.fixes_applied,
        duration_ms=remark_ms,
    )
    await _cache_set(cache_key, result, max_items=cache_size)
    return _clone_result(result)


def _fallback_result(raw_markdown: str) -> RemarkResult:
    """remark 不可用时的降级结果。"""
    return RemarkResult(
        mdast={},
        clean_markdown=raw_markdown,
        html="",
        toc=[],
        reading_time_minutes=max(1, len(raw_markdown) // 1500),
        reading_time_words=len(raw_markdown.split()),
        fixes_applied=0,
    )


def _build_remark_result(data: dict, *, raw_markdown: str) -> RemarkResult:
    toc_nodes = [
        TOCNode(
            id=item.get("id", ""),
            title=item.get("title", ""),
            level=item.get("level", 1),
            anchor=item.get("anchor", ""),
        )
        for item in data.get("toc", [])
        if isinstance(item, dict)
    ]
    rt = data.get("readingTime", {})
    return RemarkResult(
        mdast=data.get("mdast", {}),
        clean_markdown=data.get("cleanMarkdown", raw_markdown),
        html=data.get("html", ""),
        toc=toc_nodes,
        reading_time_minutes=rt.get("minutes", 1),
        reading_time_words=rt.get("words", 0),
        fixes_applied=data.get("fixes", {}).get("appliedCount", 0),
    )


async def _invoke_remark_worker(*, payload: str, script_path: str, timeout: int) -> dict | None:
    global _WORKER_PROC, _WORKER_SCRIPT_PATH

    async with _WORKER_LOCK:
        proc = await _ensure_worker(script_path)
        if proc.stdin is None or proc.stdout is None:
            await _reset_worker()
            return None

        try:
            proc.stdin.write(payload.encode("utf-8") + b"\n")
            await proc.stdin.drain()
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("normalize.remark_timeout", timeout=timeout)
            await _reset_worker()
            return None
        except Exception as exc:
            logger.warning("normalize.remark_worker_io_failed", error=str(exc)[:200])
            await _reset_worker()
            return None

        if not line:
            logger.warning("normalize.remark_worker_eof")
            await _reset_worker()
            return None

        try:
            return json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            logger.warning("normalize.remark_worker_json_error", error=str(exc))
            await _reset_worker()
            return None


async def _ensure_worker(script_path: str) -> asyncio.subprocess.Process:
    global _WORKER_PROC, _WORKER_SCRIPT_PATH

    if (
        _WORKER_PROC is not None
        and _WORKER_PROC.returncode is None
        and _WORKER_SCRIPT_PATH == script_path
    ):
        return _WORKER_PROC

    await _reset_worker()

    _WORKER_PROC = await asyncio.create_subprocess_exec(
        "node",
        script_path,
        "--server",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _WORKER_SCRIPT_PATH = script_path
    return _WORKER_PROC


async def _reset_worker() -> None:
    global _WORKER_PROC, _WORKER_SCRIPT_PATH

    if _WORKER_PROC is not None and _WORKER_PROC.returncode is None:
        _WORKER_PROC.kill()
        try:
            await asyncio.wait_for(_WORKER_PROC.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
    _WORKER_PROC = None
    _WORKER_SCRIPT_PATH = None


def _clone_result(result: RemarkResult) -> RemarkResult:
    return RemarkResult(
        mdast=deepcopy(result.mdast),
        clean_markdown=result.clean_markdown,
        html=result.html,
        toc=[TOCNode(id=n.id, title=n.title, level=n.level, anchor=n.anchor) for n in result.toc],
        reading_time_minutes=result.reading_time_minutes,
        reading_time_words=result.reading_time_words,
        fixes_applied=result.fixes_applied,
    )


async def _cache_get(cache_key: str) -> RemarkResult | None:
    async with _RESULT_CACHE_LOCK:
        cached = _RESULT_CACHE.get(cache_key)
        if cached is None:
            return None
        _RESULT_CACHE.move_to_end(cache_key)
        return _clone_result(cached)


async def _cache_set(cache_key: str, result: RemarkResult, *, max_items: int) -> None:
    async with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[cache_key] = _clone_result(result)
        _RESULT_CACHE.move_to_end(cache_key)
        while len(_RESULT_CACHE) > max_items:
            _RESULT_CACHE.popitem(last=False)
