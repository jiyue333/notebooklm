"""Phase 1b — MIME 检测 (python-magic) + 路由决策。"""

from __future__ import annotations

import hashlib

import structlog

from app.infra.providers.tika.client import detect_mime_async
from app.modules.ingest.types import DocRoute, FetchedContent, TikaMetadata

logger = structlog.get_logger(__name__)

_MIME_ROUTE: list[tuple[str, DocRoute]] = [
    ("application/pdf", DocRoute.PDF),
    ("text/html", DocRoute.HTML),
    ("application/xhtml+xml", DocRoute.HTML),
    ("application/msword", DocRoute.OFFICE),
    ("application/vnd.openxmlformats-officedocument", DocRoute.OFFICE),
    ("application/vnd.ms-powerpoint", DocRoute.OFFICE),
    ("application/vnd.ms-excel", DocRoute.OFFICE),
    ("image/png", DocRoute.IMAGE),
    ("image/jpeg", DocRoute.IMAGE),
    ("image/jpg", DocRoute.IMAGE),
    ("image/webp", DocRoute.IMAGE),
    ("text/plain", DocRoute.TEXT),
    ("text/markdown", DocRoute.TEXT),
    ("text/x-markdown", DocRoute.TEXT),
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
) -> FetchedContent:
    """检测 MIME 类型并生成路由决策。"""

    mime_type = await detect_mime_async(raw_bytes)
    route = _resolve_route(mime_type, file_name)
    content_hash = hashlib.sha256(raw_bytes).hexdigest()

    return FetchedContent(
        raw_bytes=raw_bytes,
        content_hash=content_hash,
        tika=TikaMetadata(mime_type=mime_type),
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

    logger.warning("detect.unknown_type", mime=mime_type, file_name=file_name)
    return DocRoute.HTML


def _get_ext(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:].lower() if dot >= 0 else ""
