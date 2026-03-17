"""Stage D – Parse to Markdown.

Routes the document to a single parser based on DocRoute and produces
a FusedDocument with clean markdown.

Parser routing:
  HTML   → DripperClient (LLM / API / local) → trafilatura fallback
  PDF    → MinerUClient
  OFFICE → MinerUClient
  IMAGE  → MinerUClient (with OCR)
  TEXT   → direct pass-through

All infra clients read configuration from ``get_settings()`` internally,
so this module does not need to thread config parameters.
"""

from __future__ import annotations

import re

import structlog

from app.modules.ingest.parsers.file_parser import parse_file
from app.modules.ingest.parsers.html_parser import parse_html
from app.modules.ingest.parsers.text_parser import decode_text_bytes, parse_text
from app.modules.ingest.pipeline.types import (
    CanonicalDoc,
    DocCategory,
    DocRoute,
    FusedDocument,
)

logger = structlog.get_logger(__name__)


async def parse_to_markdown(
    doc: CanonicalDoc,
    route: DocRoute,
) -> FusedDocument | None:
    """Parse the document into a FusedDocument with clean markdown."""

    if route.category == DocCategory.TEXT:
        return _parse_text(doc)

    if route.category == DocCategory.HTML:
        return await _parse_html(doc)

    if route.category in (DocCategory.PDF, DocCategory.OFFICE, DocCategory.IMAGE):
        return await _parse_file(doc)

    logger.warning("ingest.parse.unknown_route", category=route.category.value)
    return _fallback_text(doc)


def _parse_text(doc: CanonicalDoc) -> FusedDocument | None:
    raw_text = doc.artifact.raw_text
    if not raw_text and doc.artifact.raw_bytes:
        raw_text = decode_text_bytes(doc.artifact.raw_bytes)
    if not raw_text:
        return None

    candidate = parse_text(raw_text, title=None)
    if not candidate:
        return None

    return _to_fused(candidate)


async def _parse_html(doc: CanonicalDoc) -> FusedDocument | None:
    url = doc.artifact.source_url or ""
    candidate = await parse_html(url, raw_html=doc.artifact.raw_bytes or None)
    if not candidate:
        return None

    return _to_fused(candidate)


async def _parse_file(doc: CanonicalDoc) -> FusedDocument | None:
    candidate = await parse_file(
        doc.artifact.raw_bytes,
        file_name=doc.artifact.file_name,
        file_ext=doc.artifact.file_ext,
    )
    if not candidate:
        return None

    return _to_fused(candidate)


def _fallback_text(doc: CanonicalDoc) -> FusedDocument | None:
    """Last resort – try to decode as text."""
    if doc.artifact.raw_bytes:
        text = decode_text_bytes(doc.artifact.raw_bytes)
        if text.strip():
            candidate = parse_text(text)
            if candidate:
                return _to_fused(candidate)
    return None


def _to_fused(candidate) -> FusedDocument:
    """Convert a ParseCandidate into a FusedDocument with markdown cleanup."""

    clean = _clean_markdown(candidate.markdown)
    return FusedDocument(
        clean_markdown=clean,
        title=candidate.title or "",
        author=candidate.author,
        published_at=candidate.published_at,
        description=candidate.description,
        language=candidate.language,
        word_count=len(clean.split()),
        primary_parser=candidate.parser_name,
        metadata=candidate.metadata,
    )


def _clean_markdown(md: str) -> str:
    text = md.strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = text.replace("\x00", "")
    return text.strip() + "\n"
