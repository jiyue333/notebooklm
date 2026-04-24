"""Phase 2 — 解析层：MinerU Cloud batch API 统一解析 → raw markdown。

路由策略:
  TEXT               → 直通 (不走 MinerU)
  URL + 有 batch_id  → 直接 poll 已提交的 batch (search import 批量化)
  URL + 无 batch_id  → URL batch of 1，失败回退文件 batch of 1
  FILE               → 文件 batch of 1
"""

from __future__ import annotations

import asyncio
import html
import re
from collections import OrderedDict
from hashlib import sha256
from threading import Lock
from time import monotonic, perf_counter
from typing import Awaitable, Callable

import structlog

from app.core.config import get_settings
from app.infra.providers.mineru.client import MinerUCloudClient
from app.modules.ingest.types import DocRoute, FetchedContent

logger = structlog.get_logger(__name__)

_ROUTE_MODEL_MAP: dict[DocRoute, str] = {
    DocRoute.PDF: "vlm",
    DocRoute.OFFICE: "vlm",
    DocRoute.IMAGE: "vlm",
    DocRoute.HTML: "MinerU-HTML",
}

_MINERU_SEMAPHORE: asyncio.Semaphore | None = None
_MINERU_STATE_LOCK = Lock()
_MINERU_FAILURE_STREAK = 0
_MINERU_CIRCUIT_OPEN_UNTIL = 0.0
_TIMED_OUT_BATCHES: set[str] = set()

_PARSE_CACHE_LOCK = Lock()
_PARSE_RESULT_CACHE: OrderedDict[str, str] = OrderedDict()


async def parse_to_markdown(
    content: FetchedContent,
    *,
    mineru_batch_id: str | None = None,
    mineru_data_id: str | None = None,
    mineru_client: MinerUCloudClient | None = None,
) -> str | None:
    """将内容转为 raw markdown，失败返回 None。

    mineru_batch_id / mineru_data_id: search import 在 API 层预提交的 batch，
    worker 只需 poll + download，不重复提交。
    """

    if content.route == DocRoute.TEXT:
        return content.raw_bytes.decode("utf-8", errors="replace")

    cache_key = _build_cache_key(content)
    if cache_key:
        cached = _read_cached_markdown(cache_key)
        if cached:
            logger.debug(
                "parse.cache_hit",
                route=content.route.value,
                key=cache_key[:24],
                result_chars=len(cached),
            )
            return cached

    client = mineru_client or MinerUCloudClient()
    model_version = _ROUTE_MODEL_MAP.get(content.route, "vlm")
    file_name = content.file_name or f"input{_default_ext(content.route)}"
    data_id = mineru_data_id or "single"

    logger.info(
        "parse.start",
        route=content.route.value,
        model=model_version,
        has_batch=bool(mineru_batch_id),
        source_url=content.source_url,
    )

    # ====== 已有 batch (search import 预提交) ======
    if mineru_batch_id and mineru_data_id:
        md = await _run_mineru_call(
            "poll_existing_batch",
            lambda: _poll_existing_batch(client, mineru_batch_id, mineru_data_id),
        )
        if md:
            if cache_key:
                _write_cached_markdown(cache_key, md)
            return md
        logger.warning(
            "parse.poll_batch_fallthrough",
            batch_id=mineru_batch_id,
            data_id=mineru_data_id,
            route=content.route.value,
        )
        # poll 失败，fall through 到 URL/FILE 回退链

    # ====== URL 来源: URL batch 优先，回退文件 batch ======
    if content.source_url:
        url_model = _infer_model_from_url(content.source_url) or model_version
        md = await _run_mineru_call(
            "parse_url_batch",
            lambda: _try_url_batch(
                client,
                content.source_url,
                data_id=data_id,
                model_version=url_model,
            ),
        )
        if md:
            if cache_key:
                _write_cached_markdown(cache_key, md)
            return md
        # URL batch 失败 + 有 bytes → 回退文件 batch
        if content.raw_bytes:
            logger.info("parse.url_failed_fallback_upload", url=content.source_url)
            md = await _run_mineru_call(
                "parse_file_batch_fallback",
                lambda: client.parse_file(
                    content.raw_bytes,
                    file_name=file_name,
                    data_id=data_id,
                    model_version=model_version,
                ),
            )
            if md:
                if cache_key:
                    _write_cached_markdown(cache_key, md)
                return md
            if content.route == DocRoute.HTML:
                fallback = _fallback_html_bytes_to_markdown(content.raw_bytes, source_url=content.source_url)
                if fallback:
                    logger.warning("parse.local_html_fallback", url=content.source_url)
                    if cache_key:
                        _write_cached_markdown(cache_key, fallback)
                    return fallback
            fallback = _fallback_binary_bytes_to_markdown(
                content.raw_bytes,
                file_name=file_name,
                source_url=content.source_url,
            )
            if fallback:
                logger.warning("parse.local_binary_fallback", url=content.source_url)
                if cache_key:
                    _write_cached_markdown(cache_key, fallback)
                return fallback
        return None

    # ====== FILE 来源: 文件 batch ======
    md = await _run_mineru_call(
        "parse_file_batch",
        lambda: client.parse_file(
            content.raw_bytes,
            file_name=file_name,
            data_id=data_id,
            model_version=model_version,
        ),
    )
    if md:
        if cache_key:
            _write_cached_markdown(cache_key, md)
        return md
    fallback = _fallback_binary_bytes_to_markdown(content.raw_bytes, file_name=file_name, source_url=None)
    if fallback:
        logger.warning("parse.local_binary_fallback", file_name=file_name)
        if cache_key:
            _write_cached_markdown(cache_key, fallback)
        return fallback
    return None


async def _poll_existing_batch(
    client: MinerUCloudClient,
    batch_id: str,
    data_id: str,
) -> str | None:
    """poll 已提交的 batch，找到 data_id 对应的结果并下载 markdown。"""
    if batch_id in _TIMED_OUT_BATCHES:
        logger.warning("parse.skip_timed_out_batch", batch_id=batch_id, data_id=data_id)
        return None
    results = await client.poll_batch(batch_id, target_data_id=data_id)
    if not results:
        _TIMED_OUT_BATCHES.add(batch_id)
        return None
    item = next((r for r in results if r.data_id == data_id), None)
    if item and item.state == "done" and item.zip_url:
        return await client.download_markdown(item.zip_url)
    if item:
        logger.warning("parse.batch_item_failed", data_id=data_id, err=item.err_msg)
    return None


async def _try_url_batch(
    client: MinerUCloudClient,
    source_url: str,
    *,
    data_id: str,
    model_version: str,
) -> str | None:
    try:
        return await client.parse_url(
            source_url, data_id=data_id, model_version=model_version,
        )
    except Exception as exc:
        logger.info("parse.url_batch_failed", url=source_url, error=str(exc)[:200])
        return None


_MINERU_SLOW_CALL_MS = 30_000  # 单次调用超过此值打 warning


async def _run_mineru_call(
    op_name: str,
    task_factory: Callable[[], Awaitable[str | None]],
) -> str | None:
    if _is_mineru_circuit_open():
        logger.warning("parse.mineru_circuit_open", operation=op_name)
        return None

    semaphore = _get_mineru_semaphore()
    t0 = perf_counter()
    async with semaphore:
        wait_ms = round((perf_counter() - t0) * 1000, 2)
        call_t0 = perf_counter()
        try:
            result = await task_factory()
        except Exception as exc:  # pragma: no cover - 依赖外部 provider
            duration_ms = round((perf_counter() - call_t0) * 1000, 2)
            _record_mineru_failure(op_name=op_name, reason=str(exc)[:200] or "unknown")
            logger.warning(
                "parse.mineru_call_failed",
                operation=op_name,
                error=str(exc)[:200],
                duration_ms=duration_ms,
                semaphore_wait_ms=wait_ms,
            )
            return None
        duration_ms = round((perf_counter() - call_t0) * 1000, 2)

    total_ms = round((perf_counter() - t0) * 1000, 2)
    log_fn = logger.warning if total_ms > _MINERU_SLOW_CALL_MS else logger.debug
    log_fn(
        "parse.mineru_call_done",
        operation=op_name,
        success=bool(result),
        duration_ms=duration_ms,
        semaphore_wait_ms=wait_ms,
        total_ms=total_ms,
        result_chars=len(result) if result else 0,
    )

    if result:
        _record_mineru_success()
        return result

    _record_mineru_failure(op_name=op_name, reason="empty_result")
    return None


def _infer_model_from_url(url: str) -> str | None:
    """从 URL 后缀推断 MinerU model_version。"""
    from urllib.parse import urlparse
    path = urlparse(url).path.lower().rstrip("/")

    _EXT_MODEL = {
        ".pdf": "vlm", ".doc": "vlm", ".docx": "vlm",
        ".ppt": "vlm", ".pptx": "vlm",
        ".png": "vlm", ".jpg": "vlm", ".jpeg": "vlm",
        ".html": "MinerU-HTML", ".htm": "MinerU-HTML",
    }
    for ext, model in _EXT_MODEL.items():
        if path.endswith(ext):
            return model

    # 无明确文件后缀 → 大概率是网页
    if "." not in path.rsplit("/", 1)[-1]:
        return "MinerU-HTML"
    return None


def _default_ext(route: DocRoute) -> str:
    return {
        DocRoute.PDF: ".pdf",
        DocRoute.OFFICE: ".docx",
        DocRoute.IMAGE: ".png",
        DocRoute.HTML: ".html",
    }.get(route, ".bin")


def _get_mineru_semaphore() -> asyncio.Semaphore:
    global _MINERU_SEMAPHORE
    if _MINERU_SEMAPHORE is None:
        limit = max(1, int(get_settings().mineru_max_concurrency))
        _MINERU_SEMAPHORE = asyncio.Semaphore(limit)
    return _MINERU_SEMAPHORE


def _is_mineru_circuit_open() -> bool:
    with _MINERU_STATE_LOCK:
        return monotonic() < _MINERU_CIRCUIT_OPEN_UNTIL


def _record_mineru_success() -> None:
    global _MINERU_FAILURE_STREAK, _MINERU_CIRCUIT_OPEN_UNTIL
    with _MINERU_STATE_LOCK:
        _MINERU_FAILURE_STREAK = 0
        _MINERU_CIRCUIT_OPEN_UNTIL = 0.0


def _record_mineru_failure(*, op_name: str, reason: str) -> None:
    global _MINERU_FAILURE_STREAK, _MINERU_CIRCUIT_OPEN_UNTIL
    settings = get_settings()
    threshold = max(1, int(settings.mineru_circuit_breaker_failures))
    cooldown = max(1, int(settings.mineru_circuit_breaker_cooldown_seconds))

    with _MINERU_STATE_LOCK:
        _MINERU_FAILURE_STREAK += 1
        failure_streak = _MINERU_FAILURE_STREAK
        if _MINERU_FAILURE_STREAK >= threshold:
            _MINERU_CIRCUIT_OPEN_UNTIL = monotonic() + cooldown
            _MINERU_FAILURE_STREAK = 0
            logger.warning(
                "parse.mineru_circuit_opened",
                operation=op_name,
                reason=reason,
                cooldown_seconds=cooldown,
            )
            return
    logger.warning("parse.mineru_failure", operation=op_name, reason=reason, failure_streak=failure_streak)


def _build_cache_key(content: FetchedContent) -> str | None:
    route = content.route.value
    if content.content_hash:
        return f"{route}:hash:{content.content_hash}"
    if content.source_url:
        url_hash = sha256(content.source_url.encode("utf-8")).hexdigest()
        return f"{route}:url:{url_hash}"
    return None


def _read_cached_markdown(cache_key: str) -> str | None:
    with _PARSE_CACHE_LOCK:
        value = _PARSE_RESULT_CACHE.get(cache_key)
        if value is None:
            return None
        _PARSE_RESULT_CACHE.move_to_end(cache_key)
        return value


def _write_cached_markdown(cache_key: str, markdown: str) -> None:
    max_size = max(16, int(get_settings().mineru_result_cache_size))
    with _PARSE_CACHE_LOCK:
        _PARSE_RESULT_CACHE[cache_key] = markdown
        _PARSE_RESULT_CACHE.move_to_end(cache_key)
        while len(_PARSE_RESULT_CACHE) > max_size:
            _PARSE_RESULT_CACHE.popitem(last=False)


def _fallback_html_bytes_to_markdown(raw_bytes: bytes, *, source_url: str | None) -> str:
    text = raw_bytes.decode("utf-8", errors="replace")
    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    replacements = [
        (r"(?i)<br\s*/?>", "\n"),
        (r"(?i)</p\s*>", "\n\n"),
        (r"(?i)</div\s*>", "\n\n"),
        (r"(?i)</section\s*>", "\n\n"),
        (r"(?i)</article\s*>", "\n\n"),
        (r"(?i)</li\s*>", "\n"),
        (r"(?is)<li[^>]*>", "- "),
    ]
    for pattern, replacement in replacements:
        stripped = re.sub(pattern, replacement, stripped)

    for level in range(6, 0, -1):
        stripped = re.sub(
            rf"(?is)<h{level}[^>]*>(.*?)</h{level}>",
            lambda match: f"\n\n{'#' * level} {_strip_html_inline(match.group(1))}\n\n",
            stripped,
        )

    stripped = re.sub(r"(?is)<title[^>]*>(.*?)</title>", lambda m: f"# {_strip_html_inline(m.group(1))}\n\n", stripped)
    stripped = re.sub(r"(?is)<[^>]+>", " ", stripped)
    stripped = html.unescape(stripped)
    stripped = re.sub(r"\r\n?", "\n", stripped)
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    if source_url:
        stripped = f"来源：{source_url}\n\n{stripped}".strip()
    return stripped


def _fallback_binary_bytes_to_markdown(
    raw_bytes: bytes,
    *,
    file_name: str | None,
    source_url: str | None,
) -> str | None:
    utf8_text = raw_bytes.decode("utf-8", errors="ignore")
    utf8_text = re.sub(r"\r\n?", "\n", utf8_text)
    utf8_text = re.sub(r"\n{3,}", "\n\n", utf8_text).strip()

    extracted = utf8_text
    if len(extracted) < 120:
        latin = raw_bytes.decode("latin-1", errors="ignore")
        snippets = re.findall(r"[A-Za-z0-9][A-Za-z0-9 ,.;:()/_\-]{24,}", latin)
        extracted = "\n".join(snippets[:40]).strip()

    if len(extracted) < 120:
        return None

    title = (file_name or "导入文档").strip()
    lines = [f"# {title}", "", "> MinerU 解析暂不可用，以下为降级文本抽取结果。", ""]
    if source_url:
        lines.extend([f"来源：{source_url}", ""])
    lines.append(extracted[:12000])
    return "\n".join(lines).strip()


def _strip_html_inline(value: str) -> str:
    text = re.sub(r"(?is)<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
