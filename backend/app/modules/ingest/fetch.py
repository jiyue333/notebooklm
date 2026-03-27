"""Phase 1a — 拉取内容。

按 InputType 获取原始 bytes：
  URL / SEARCH_RESULT → httpx 下载
  FILE                → 从 file_store 或 IngestInput.file_bytes 读取
  TEXT                → encode 为 bytes
"""

from __future__ import annotations

import httpx
import structlog

from app.modules.ingest.types import IngestInput, InputType

# 与 detect._EXT_ROUTE 同步：仅这些后缀才信任 URL 路径中的文件名（避免 arXiv id 等带点串）
_TRUSTED_PATH_EXTS: frozenset[str] = frozenset(
    (".pdf", ".html", ".htm", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".txt", ".md")
)

logger = structlog.get_logger(__name__)

_FETCH_TIMEOUT = 30
_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


async def fetch_content(inp: IngestInput) -> tuple[bytes, str | None]:
    """返回 (raw_bytes, file_name)。"""

    if inp.input_type == InputType.TEXT:
        text = inp.raw_text or ""
        file_name = inp.file_name or "input.md"
        return text.encode("utf-8"), file_name

    if inp.input_type == InputType.FILE:
        if inp.file_bytes:
            return inp.file_bytes, inp.file_name
        if inp.file_name:
            from app.infra.storage.file_store import load_file_bytes
            data = load_file_bytes(inp.file_name)
            return data, inp.file_name
        raise ValueError("FILE 类型需要 file_bytes 或 file_name")

    # URL / SEARCH_RESULT
    if not inp.source_url:
        raise ValueError(f"{inp.input_type.value} 类型需要 source_url")

    try:
        return await _download_url(inp.source_url, verify=True)
    except httpx.HTTPError as exc:
        if _should_retry_without_tls_verification(inp.source_url, exc):
            logger.warning(
                "fetch.ssl_verify_failed_retry_insecure",
                url=inp.source_url,
                error=str(exc)[:200],
            )
            return await _download_url(inp.source_url, verify=False)
        raise


async def _download_url(source_url: str, *, verify: bool) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True, verify=verify) as http:
        resp = await http.get(source_url)
        resp.raise_for_status()
        data = resp.content
        if len(data) > _MAX_DOWNLOAD_BYTES:
            raise ValueError(f"文件过大: {len(data)} bytes")
        file_name = _guess_filename(source_url, resp.headers.get("content-type", ""))
        return data, file_name


def _should_retry_without_tls_verification(source_url: str, exc: Exception) -> bool:
    if not source_url.lower().startswith("https://"):
        return False
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)


def _guess_filename(url: str, content_type: str) -> str:
    """路径最后一段仅在扩展名可信时使用；arXiv 等 `NNNN.NNNNN` 会误判为文件名，需走 MIME。"""
    from urllib.parse import urlparse

    path = urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1] if "/" in path else ""

    if name:
        dot = name.rfind(".")
        if dot >= 0 and name[dot:].lower() in _TRUSTED_PATH_EXTS:
            return name

    ext_map = {
        "text/html": ".html",
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }
    for mime, ext in ext_map.items():
        if mime in content_type:
            return f"download{ext}"

    return "download.html"
