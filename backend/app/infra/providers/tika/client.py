"""Apache Tika 客户端 — MIME 检测与文档元数据提取。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import structlog
from tika import detector as tika_detector  # type: ignore[import-untyped]
from tika import parser as tika_parser  # type: ignore[import-untyped]

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class TikaResult:
    mime_type: str = "application/octet-stream"
    language: str | None = None
    title: str | None = None
    author: str | None = None
    page_count: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class TikaClient:
    """通过 ``tika`` Python 包做 MIME 检测 + 元数据提取。"""

    def __init__(self, *, server_url: str | None = None) -> None:
        self._server_url = server_url or ""

    async def detect(self, raw_bytes: bytes) -> TikaResult:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._detect_sync, raw_bytes)

    # ------------------------------------------------------------------

    def _detect_sync(self, raw_bytes: bytes) -> TikaResult:
        result = TikaResult()

        try:
            kw = {"serverEndpoint": self._server_url} if self._server_url else {}
            mime = tika_detector.from_buffer(raw_bytes, **kw)
            if mime:
                result.mime_type = mime.strip()
        except Exception as exc:
            logger.warning("tika.detect_failed", error=str(exc))

        try:
            kw = {"serverEndpoint": self._server_url} if self._server_url else {}
            parsed = tika_parser.from_buffer(raw_bytes, **kw, xmlContent=False)
            meta: dict = parsed.get("metadata") or {}
            result.metadata = {k: str(v) for k, v in meta.items() if v}
            result.title = _first(meta, "dc:title", "title")
            result.author = _first(meta, "dc:creator", "meta:author", "Author")
            result.language = _first(meta, "dc:language", "Content-Language", "language")
            pages = _first(meta, "xmpTPg:NPages", "meta:page-count", "Page-Count")
            if pages and str(pages).isdigit():
                result.page_count = int(pages)
        except Exception as exc:
            logger.warning("tika.parse_metadata_failed", error=str(exc))

        return result


def _first(meta: dict, *keys: str) -> str | None:
    for k in keys:
        v = meta.get(k)
        if v:
            return str(v) if not isinstance(v, str) else v
    return None
