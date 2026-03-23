"""Phase 1b — Tika MIME 检测 + 路由决策。"""

from __future__ import annotations

import hashlib

import structlog

from app.infra.providers.tika.client import TikaClient, TikaResult
from app.modules.ingest.types import DocRoute, FetchedContent, TikaMetadata

logger = structlog.get_logger(__name__)

_MIME_ROUTE: list[tuple[str, DocRoute]] = [
    ("application/pdf", DocRoute.PDF),
    ("text/html", DocRoute.HTML),
    ("application/xhtml+xml", DocRoute.HTML),
    ("application/msword", DocRoute.OFFICE),
    ("application/vnd.openxmlformats-officedocument", DocRoute.OFFICE),
    ("application/vnd.ms-powerpoint", DocRoute.OFFICE),
    ("image/png", DocRoute.IMAGE),
    ("image/jpeg", DocRoute.IMAGE),
    ("image/jpg", DocRoute.IMAGE),
    ("image/webp", DocRoute.IMAGE),
    ("text/plain", DocRoute.TEXT),
    ("text/markdown", DocRoute.TEXT),
]

_EXT_ROUTE: dict[str, DocRoute] = {
    ".pdf": DocRoute.PDF,
    ".html": DocRoute.HTML,
    ".htm": DocRoute.HTML,
    ".doc": DocRoute.OFFICE,
    ".docx": DocRoute.OFFICE,
    ".ppt": DocRoute.OFFICE,
    ".pptx": DocRoute.OFFICE,
    ".png": DocRoute.IMAGE,
    ".jpg": DocRoute.IMAGE,
    ".jpeg": DocRoute.IMAGE,
    ".txt": DocRoute.TEXT,
    ".md": DocRoute.TEXT,
}


async def detect_and_route(
    raw_bytes: bytes,
    *,
    file_name: str | None = None,
    source_url: str | None = None,
    tika_client: TikaClient | None = None,
) -> FetchedContent:
    """检测 MIME 类型并生成路由决策。"""

    client = tika_client or TikaClient()
    tika_result = await client.detect(raw_bytes)

    route = _resolve_route(tika_result.mime_type, file_name)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    tika_meta = TikaMetadata(
        mime_type=tika_result.mime_type,
        language=tika_result.language,
        title=tika_result.title,
        author=tika_result.author,
        page_count=tika_result.page_count,
    )

    return FetchedContent(
        raw_bytes=raw_bytes,
        content_hash=content_hash,
        tika=tika_meta,
        route=route,
        source_url=source_url,
        file_name=file_name,
    )


def _resolve_route(mime_type: str, file_name: str | None) -> DocRoute:
    """优先按 MIME 路由，MIME 不明确时回退到扩展名。"""

    mime_lower = mime_type.lower()
    for prefix, route in _MIME_ROUTE:
        if mime_lower.startswith(prefix):
            return route

    if file_name:
        ext = _get_ext(file_name)
        if ext in _EXT_ROUTE:
            return _EXT_ROUTE[ext]

    # 无法判断时默认当 HTML 走 MinerU
    logger.warning("detect.unknown_type", mime=mime_type, file_name=file_name)
    return DocRoute.HTML


def _get_ext(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""
