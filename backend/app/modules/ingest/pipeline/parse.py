"""Stage D – Multi-Parser Candidate Generation.

Routes the document to one or more parsers based on the DocRoute
and collects all resulting ParseCandidates.
"""

from __future__ import annotations

import asyncio

import structlog

from app.modules.ingest.parsers.file_parser import parse_file
from app.modules.ingest.parsers.html_parser import parse_html_exa, parse_html_trafilatura
from app.modules.ingest.parsers.text_parser import decode_text_bytes, parse_text
from app.modules.ingest.pipeline.types import (
    CanonicalDoc,
    DocCategory,
    DocRoute,
    ParseCandidate,
)

logger = structlog.get_logger(__name__)


async def generate_parse_candidates(
    doc: CanonicalDoc,
    route: DocRoute,
    *,
    exa_api_key: str | None = None,
) -> list[ParseCandidate]:
    """Run the appropriate parsers and return all non-empty candidates."""

    if route.category == DocCategory.TEXT:
        return _parse_text(doc)

    if route.category == DocCategory.HTML:
        return await _parse_html(doc, exa_api_key=exa_api_key)

    if route.category in (DocCategory.PDF, DocCategory.OFFICE):
        return await _parse_file(doc, route)

    if route.category == DocCategory.IMAGE:
        return _parse_image_placeholder(doc)

    logger.warning("ingest.parse.unknown_route", category=route.category.value)
    return _fallback_text(doc)


# ── route handlers ─────────────────────────────────────────────────────────

def _parse_text(doc: CanonicalDoc) -> list[ParseCandidate]:
    raw_text = doc.artifact.raw_text
    if not raw_text and doc.artifact.raw_bytes:
        raw_text = decode_text_bytes(doc.artifact.raw_bytes)
    if not raw_text:
        return []
    candidate = parse_text(raw_text, title=None)
    return [candidate] if candidate else []


async def _parse_html(
    doc: CanonicalDoc,
    *,
    exa_api_key: str | None,
) -> list[ParseCandidate]:
    url = doc.artifact.source_url or ""
    tasks = []

    tasks.append(parse_html_trafilatura(url, raw_html=doc.artifact.raw_bytes or None))

    if exa_api_key and url:
        tasks.append(parse_html_exa(url, exa_api_key=exa_api_key))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    candidates: list[ParseCandidate] = []
    for r in results:
        if isinstance(r, ParseCandidate):
            candidates.append(r)
        elif isinstance(r, BaseException):
            logger.warning("ingest.parse.html_parser_failed", error=str(r))
    return candidates


async def _parse_file(doc: CanonicalDoc, route: DocRoute) -> list[ParseCandidate]:
    candidate = await parse_file(
        doc.artifact.raw_bytes,
        file_name=doc.artifact.file_name,
        file_ext=doc.artifact.file_ext,
    )
    return [candidate] if candidate else []


def _parse_image_placeholder(doc: CanonicalDoc) -> list[ParseCandidate]:
    title = doc.artifact.file_name or "Image"
    url = doc.artifact.source_url or ""
    markdown = f"# {title}\n\n![{title}]({url})\n"
    return [ParseCandidate(
        parser_name="image_placeholder",
        markdown=markdown,
        title=title,
        word_count=len(markdown.split()),
    )]


def _fallback_text(doc: CanonicalDoc) -> list[ParseCandidate]:
    """Last resort – try to decode as text."""
    if doc.artifact.raw_bytes:
        text = decode_text_bytes(doc.artifact.raw_bytes)
        if text.strip():
            candidate = parse_text(text)
            return [candidate] if candidate else []
    return []
