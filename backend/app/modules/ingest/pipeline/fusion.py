"""Stage F – Fusion & Repair.

Merges the best parse candidate's body with metadata from others,
then applies markdown cleanup.  LLM-based repair is flagged but
deferred to a future iteration.
"""

from __future__ import annotations

import re

from app.modules.ingest.pipeline.types import FusedDocument, ScoredParseCandidate


def fuse(ranked: list[ScoredParseCandidate]) -> FusedDocument:
    """Produce a ``FusedDocument`` from ranked parse candidates."""

    if not ranked:
        return FusedDocument(clean_markdown="", title="", quality_score=0.0)

    best = ranked[0]
    body = best.candidate.markdown

    # Merge metadata from secondary candidates when primary is missing.
    title = best.candidate.title
    author = best.candidate.author
    published_at = best.candidate.published_at
    description = best.candidate.description
    language = best.candidate.language

    for alt in ranked[1:]:
        c = alt.candidate
        if not title and c.title:
            title = c.title
        if not author and c.author:
            author = c.author
        if not published_at and c.published_at:
            published_at = c.published_at
        if not description and c.description:
            description = c.description
        if not language and c.language:
            language = c.language

    clean = _clean_markdown(body)

    return FusedDocument(
        clean_markdown=clean,
        title=title or "",
        author=author,
        published_at=published_at,
        description=description,
        language=language,
        word_count=len(clean.split()),
        quality_score=best.quality.total,
        primary_parser=best.candidate.parser_name,
        metadata=best.candidate.metadata,
    )


# ── markdown cleanup ───────────────────────────────────────────────────────

def _clean_markdown(md: str) -> str:
    text = md.strip()
    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ consecutive blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    # Remove null bytes
    text = text.replace("\x00", "")
    return text.strip() + "\n"
