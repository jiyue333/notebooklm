"""Phase 2 — 解析层：MinerU Cloud batch API 统一解析 → raw markdown。

路由策略:
  TEXT               → 直通 (不走 MinerU)
  URL + 有 batch_id  → 直接 poll 已提交的 batch (search import 批量化)
  URL + 无 batch_id  → URL batch of 1，失败回退文件 batch of 1
  FILE               → 文件 batch of 1
"""

from __future__ import annotations

import html
import re

import structlog

from app.infra.providers.mineru.client import MinerUCloudClient
from app.modules.ingest.types import DocRoute, FetchedContent

logger = structlog.get_logger(__name__)

_ROUTE_MODEL_MAP: dict[DocRoute, str] = {
    DocRoute.PDF: "vlm",
    DocRoute.OFFICE: "vlm",
    DocRoute.IMAGE: "vlm",
    DocRoute.HTML: "MinerU-HTML",
}


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
        return await _poll_existing_batch(client, mineru_batch_id, mineru_data_id)

    # ====== URL 来源: URL batch 优先，回退文件 batch ======
    if content.source_url:
        url_model = _infer_model_from_url(content.source_url) or model_version
        md = await _try_url_batch(client, content.source_url, data_id=data_id, model_version=url_model)
        if md:
            return md
        # URL batch 失败 + 有 bytes → 回退文件 batch
        if content.raw_bytes:
            logger.info("parse.url_failed_fallback_upload", url=content.source_url)
            try:
                md = await client.parse_file(
                    content.raw_bytes, file_name=file_name,
                    data_id=data_id, model_version=model_version,
                )
                if md:
                    return md
            except Exception as exc:
                logger.info("parse.file_batch_failed", url=content.source_url, error=str(exc)[:200])
            if content.route == DocRoute.HTML:
                fallback = _fallback_html_bytes_to_markdown(content.raw_bytes, source_url=content.source_url)
                if fallback:
                    logger.warning("parse.local_html_fallback", url=content.source_url)
                    return fallback
        return None

    # ====== FILE 来源: 文件 batch ======
    return await client.parse_file(
        content.raw_bytes, file_name=file_name,
        data_id=data_id, model_version=model_version,
    )


async def _poll_existing_batch(
    client: MinerUCloudClient,
    batch_id: str,
    data_id: str,
) -> str | None:
    """poll 已提交的 batch，找到 data_id 对应的结果并下载 markdown。"""
    results = await client.poll_batch(batch_id, target_data_id=data_id)
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


def _strip_html_inline(value: str) -> str:
    text = re.sub(r"(?is)<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()
