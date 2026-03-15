"""Stage B – Canonicalization & Dedup.

Checks whether the artifact already exists in the notebook (by
content hash, URL hash, DOI, or arXiv id) and builds a dedupe key.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

from app.modules.ingest.pipeline.types import CanonicalDoc, FetchedArtifact

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,}/[^\s]+)")


def canonicalize(
    artifact: FetchedArtifact,
    existing_dedupe_keys: set[str],
) -> CanonicalDoc:
    """Build a ``CanonicalDoc`` and flag duplicates."""

    canonical_url = _normalize_url(artifact.source_url) if artifact.source_url else None
    doi = _extract_doi(artifact.source_url)
    arxiv_id = _extract_arxiv(artifact.source_url)

    dedupe_key = _build_dedupe_key(artifact, canonical_url, doi, arxiv_id)
    is_dup = dedupe_key in existing_dedupe_keys

    return CanonicalDoc(
        artifact=artifact,
        dedupe_key=dedupe_key,
        is_duplicate=is_dup,
        doi=doi,
        arxiv_id=arxiv_id,
        canonical_url=canonical_url,
    )


# ── helpers ────────────────────────────────────────────────────────────────

def _build_dedupe_key(
    artifact: FetchedArtifact,
    canonical_url: str | None,
    doi: str | None,
    arxiv_id: str | None,
) -> str:
    if doi:
        return f"doi:{doi.lower()}"
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if canonical_url:
        return f"url:{hashlib.sha256(canonical_url.encode()).hexdigest()}"
    if artifact.content_hash:
        return f"hash:{artifact.content_hash}"
    return f"hash:{hashlib.sha256(artifact.raw_bytes).hexdigest()}"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        "",
        parsed.query,
        "",
    ))


def _extract_doi(url: str | None) -> str | None:
    if not url:
        return None
    m = _DOI_RE.search(url)
    return m.group(1).rstrip(".") if m else None


def _extract_arxiv(url: str | None) -> str | None:
    if not url:
        return None
    m = _ARXIV_RE.search(url)
    return m.group(1) if m else None
