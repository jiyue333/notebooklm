"""Stage E – Candidate Enrichment.

Infers metadata that the search provider didn't supply directly:
  - doc_type    (paper / report / blog / official / news / pdf / wiki)
  - authority_tier  (tier1 / tier2 / tier3)
  - is_primary_source
  - ingestability_score (0-1, higher = easier to parse downstream)

First version is purely rule-based (URL patterns + domain lists).
A future version can do lightweight HEAD requests or LLM classification.
"""

from __future__ import annotations

import re

from app.modules.search.pipeline.types import (
    AuthorityTier,
    CanonicalCandidate,
    DocType,
    EnrichedCandidate,
)

# ── domain classification tables ───────────────────────────────────────────

_TIER1_SUFFIXES = (".gov", ".edu", ".ac.uk", ".ac.jp", ".edu.cn")
_TIER1_DOMAINS = frozenset({
    "arxiv.org",
    "nature.com",
    "science.org",
    "nih.gov",
    "nasa.gov",
    "who.int",
    "cdc.gov",
    "pubmed.ncbi.nlm.nih.gov",
    "ieee.org",
    "acm.org",
    "springer.com",
    "sciencedirect.com",
    "openreview.net",
})

_TIER2_PATTERNS = (
    "github.com",
    "docs.",
    "developer.",
    "engineering.",
    "blog.google",
    "openai.com",
    "anthropic.com",
    "deepmind.com",
    "huggingface.co",
    "pytorch.org",
    "tensorflow.org",
)

_OFFICIAL_PATTERNS = (
    "docs.",
    "developer.",
    "/docs/",
    "/documentation/",
    "/reference/",
    "/api/",
)

_NEWS_DOMAINS = frozenset({
    "reuters.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "theguardian.com",
    "techcrunch.com",
    "theverge.com",
    "arstechnica.com",
    "wired.com",
})

_WIKI_DOMAINS = frozenset({
    "en.wikipedia.org",
    "zh.wikipedia.org",
    "ja.wikipedia.org",
})

_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/", re.IGNORECASE)
_PDF_RE = re.compile(r"\.pdf(?:\?|$)", re.IGNORECASE)


def enrich(candidates: list[CanonicalCandidate]) -> list[EnrichedCandidate]:
    """Add doc_type, authority, primary-source flag, and ingestability."""

    return [_enrich_one(c) for c in candidates]


def _enrich_one(c: CanonicalCandidate) -> EnrichedCandidate:
    domain = (c.domain or "").lower()
    url = c.canonical_url.lower()

    doc_type = _classify_doc_type(domain, url)
    authority = _classify_authority(domain)
    is_primary = _is_primary(doc_type, authority, c)
    ingestability = _estimate_ingestability(doc_type, c)

    return EnrichedCandidate(
        canonical_url=c.canonical_url,
        url_hash=c.url_hash,
        title=c.title,
        description=c.description,
        author=c.author,
        published_at=c.published_at,
        domain=c.domain,
        favicon_url=c.favicon_url,
        preview_markdown=c.preview_markdown,
        highlights=c.highlights,
        raw_payload=c.raw_payload,
        provider=c.provider,
        provider_result_id=c.provider_result_id,
        query_roles=c.query_roles,
        best_display_rank=c.best_display_rank,
        variant_count=c.variant_count,
        doc_type=doc_type,
        authority_tier=authority,
        is_primary_source=is_primary,
        ingestability_score=ingestability,
    )


# ── classifiers ────────────────────────────────────────────────────────────

def _classify_doc_type(domain: str, url: str) -> DocType:
    if _ARXIV_RE.search(url):
        return DocType.PAPER
    if domain in _WIKI_DOMAINS:
        return DocType.WIKI
    if domain in _NEWS_DOMAINS:
        return DocType.NEWS
    if _PDF_RE.search(url):
        return DocType.PDF
    if any(p in domain or p in url for p in _OFFICIAL_PATTERNS):
        return DocType.OFFICIAL
    if "blog" in domain or "blog" in url or "medium.com" in domain:
        return DocType.BLOG
    if domain.endswith((".gov", ".edu")) or domain in _TIER1_DOMAINS:
        return DocType.REPORT
    return DocType.OTHER


def _classify_authority(domain: str) -> AuthorityTier:
    if any(domain.endswith(suffix) for suffix in _TIER1_SUFFIXES):
        return AuthorityTier.TIER1
    if domain in _TIER1_DOMAINS:
        return AuthorityTier.TIER1
    if any(pat in domain for pat in _TIER2_PATTERNS):
        return AuthorityTier.TIER2
    return AuthorityTier.TIER3


def _is_primary(
    doc_type: DocType,
    authority: AuthorityTier,
    c: CanonicalCandidate,
) -> bool:
    if doc_type in (DocType.PAPER, DocType.REPORT, DocType.OFFICIAL):
        return True
    if authority == AuthorityTier.TIER1:
        return True
    if c.author and doc_type != DocType.NEWS:
        return True
    return False


def _estimate_ingestability(doc_type: DocType, c: CanonicalCandidate) -> float:
    """Heuristic 0-1 score predicting how cleanly this will parse."""

    score = 0.5

    if doc_type == DocType.PDF:
        score -= 0.15  # PDFs often need OCR / complex parsing
    if doc_type in (DocType.OFFICIAL, DocType.WIKI):
        score += 0.2  # structured HTML
    if doc_type == DocType.BLOG:
        score += 0.1  # usually clean HTML

    if c.preview_markdown and len(c.preview_markdown) > 100:
        score += 0.1  # already got content from the provider
    if c.author:
        score += 0.05
    if c.published_at:
        score += 0.05

    return max(0.0, min(1.0, score))
