"""Stage A – Fetch & Fingerprint.

Downloads or reads the raw artifact, computes a content hash,
and records HTTP metadata when applicable.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from app.modules.ingest.parsers.text_parser import decode_text_bytes
from app.modules.ingest.pipeline.types import FetchedArtifact, IngestInput, InputType

logger = structlog.get_logger(__name__)

_FETCH_TIMEOUT = 30.0


async def fetch(ingest_input: IngestInput) -> FetchedArtifact:
    """Produce a ``FetchedArtifact`` from the ingest input."""

    if ingest_input.input_type == InputType.TEXT:
        return _from_text(ingest_input)

    if ingest_input.input_type == InputType.FILE:
        return _from_file(ingest_input)

    # URL or search_result – download
    return await _from_url(ingest_input)


def _from_text(inp: IngestInput) -> FetchedArtifact:
    text = inp.raw_text or ""
    raw = text.encode("utf-8")
    return FetchedArtifact(
        raw_bytes=raw,
        content_hash=_sha256(raw),
        content_type="text/plain",
        file_name=None,
        file_ext=".txt",
        source_url=None,
        size_bytes=len(raw),
        raw_text=text,
        fetched_at=datetime.now(UTC),
    )


def _from_file(inp: IngestInput) -> FetchedArtifact:
    raw = inp.file_bytes or b""
    ext = Path(inp.file_name).suffix.lower() if inp.file_name else ""
    mime = inp.file_mime or _guess_mime(ext)

    is_text = mime.startswith("text/") or ext in (".md", ".txt", ".csv", ".tsv")
    raw_text = decode_text_bytes(raw) if is_text else None

    return FetchedArtifact(
        raw_bytes=raw,
        content_hash=_sha256(raw),
        content_type=mime,
        file_name=inp.file_name,
        file_ext=ext or None,
        source_url=inp.source_url,
        size_bytes=len(raw),
        raw_text=raw_text,
        fetched_at=datetime.now(UTC),
    )


async def _from_url(inp: IngestInput) -> FetchedArtifact:
    url = inp.source_url or ""
    if not url:
        raise ValueError("source_url is required for URL/search_result inputs")

    async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    raw = resp.content
    content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    headers = dict(resp.headers)

    ext = _ext_from_content_type(content_type) or _ext_from_url(url)
    is_text = content_type.startswith("text/")
    raw_text = raw.decode("utf-8", errors="replace") if is_text else None

    return FetchedArtifact(
        raw_bytes=raw,
        content_hash=_sha256(raw),
        content_type=content_type,
        file_name=inp.file_name,
        file_ext=ext,
        source_url=url,
        http_status=resp.status_code,
        http_headers=headers,
        size_bytes=len(raw),
        raw_text=raw_text,
        fetched_at=datetime.now(UTC),
    )


# ── helpers ────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _guess_mime(ext: str) -> str:
    mapping = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".htm": "text/html",
        ".csv": "text/csv",
        ".epub": "application/epub+zip",
    }
    return mapping.get(ext.lower(), "application/octet-stream")


def _ext_from_content_type(ct: str) -> str | None:
    mapping = {
        "text/html": ".html",
        "application/pdf": ".pdf",
        "text/plain": ".txt",
        "text/markdown": ".md",
    }
    return mapping.get(ct.lower())


def _ext_from_url(url: str) -> str | None:
    path = url.split("?")[0].split("#")[0]
    if "." in path.split("/")[-1]:
        return "." + path.split("/")[-1].rsplit(".", 1)[-1].lower()
    return None
