"""Stage D – Canonicalization & Deduplication.

Two-layer dedup per ADR-001 §4.5:
  1. Hard ID dedup  – canonical URL hash, DOI, arXiv id
  2. Soft similarity – normalised-title Jaccard > threshold → merge

The *best* variant (highest display_rank from provider) is kept and
its ``query_roles`` accumulate across all merged duplicates.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from app.modules.search.pipeline.types import CanonicalCandidate, RawCandidate

_JACCARD_THRESHOLD = 0.85
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.IGNORECASE)
_DOI_RE = re.compile(r"(10\.\d{4,}/[^\s]+)")


def canonicalize(candidates: list[RawCandidate]) -> list[CanonicalCandidate]:
    """Deduplicate and merge raw candidates into canonical ones."""

    # Phase 1 – hard-key grouping
    groups: dict[str, list[RawCandidate]] = {}
    for c in candidates:
        key = _hard_key(c)
        groups.setdefault(key, []).append(c)

    # Phase 2 – soft title merging within the remaining groups
    merged: list[_MergeAccumulator] = []
    for group in groups.values():
        best = _pick_best(group)
        acc = _MergeAccumulator.from_raw(best, group)
        _try_soft_merge(acc, merged)

    merged.sort(key=lambda a: a.best_rank)
    return [a.to_canonical() for a in merged]


# ── hard-key logic ─────────────────────────────────────────────────────────

def _hard_key(c: RawCandidate) -> str:
    """Deterministic dedup key: prefer DOI / arXiv id, fallback to URL hash."""

    arxiv = _ARXIV_RE.search(c.canonical_url)
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"

    doi = _DOI_RE.search(c.canonical_url)
    if doi:
        return f"doi:{doi.group(1).lower().rstrip('.')}"

    return f"url:{_url_hash(c.canonical_url)}"


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


# ── soft merge ─────────────────────────────────────────────────────────────

def _try_soft_merge(
    incoming: _MergeAccumulator,
    existing: list[_MergeAccumulator],
) -> None:
    """Merge *incoming* into an existing accumulator if titles are similar."""
    incoming_tokens = _title_tokens(incoming.title)
    for acc in existing:
        if _jaccard(incoming_tokens, _title_tokens(acc.title)) >= _JACCARD_THRESHOLD:
            acc.absorb(incoming)
            return
    existing.append(incoming)


def _title_tokens(title: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", title.lower())
    return set(re.findall(r"\w+", normalized))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union) if union else 0.0


# ── variant selection ──────────────────────────────────────────────────────

def _pick_best(group: list[RawCandidate]) -> RawCandidate:
    """Pick the variant with the best (lowest) display rank."""
    return min(group, key=lambda c: c.display_rank)


# ── merge accumulator ─────────────────────────────────────────────────────

class _MergeAccumulator:
    """Mutable container that gathers data from duplicate variants."""

    __slots__ = (
        "canonical_url",
        "url_hash",
        "title",
        "description",
        "author",
        "published_at",
        "domain",
        "favicon_url",
        "preview_markdown",
        "highlights",
        "raw_payload",
        "provider",
        "provider_result_id",
        "query_roles",
        "best_rank",
        "variant_count",
    )

    def __init__(self) -> None:
        self.query_roles: list = []
        self.highlights: list[str] = []
        self.variant_count: int = 0

    @classmethod
    def from_raw(cls, best: RawCandidate, group: list[RawCandidate]) -> _MergeAccumulator:
        acc = cls()
        acc.canonical_url = best.canonical_url
        acc.url_hash = _url_hash(best.canonical_url)
        acc.title = best.title
        acc.description = best.description
        acc.author = best.author
        acc.published_at = best.published_at
        acc.domain = best.domain
        acc.favicon_url = best.favicon_url
        acc.preview_markdown = best.preview_markdown
        acc.highlights = list(best.highlights)
        acc.raw_payload = best.raw_payload
        acc.provider = best.provider
        acc.provider_result_id = best.provider_result_id
        acc.best_rank = best.display_rank
        acc.variant_count = len(group)
        # accumulate all roles from the group
        seen_roles: set = set()
        for c in group:
            if c.query_role not in seen_roles:
                acc.query_roles.append(c.query_role)
                seen_roles.add(c.query_role)
        return acc

    def absorb(self, other: _MergeAccumulator) -> None:
        self.variant_count += other.variant_count
        if other.best_rank < self.best_rank:
            self.best_rank = other.best_rank
            self.title = other.title
            self.canonical_url = other.canonical_url
            self.url_hash = other.url_hash
            self.preview_markdown = other.preview_markdown or self.preview_markdown
        if not self.author and other.author:
            self.author = other.author
        if not self.published_at and other.published_at:
            self.published_at = other.published_at
        if not self.description and other.description:
            self.description = other.description
        for h in other.highlights:
            if h not in self.highlights:
                self.highlights.append(h)
        for role in other.query_roles:
            if role not in self.query_roles:
                self.query_roles.append(role)

    def to_canonical(self) -> CanonicalCandidate:
        return CanonicalCandidate(
            canonical_url=self.canonical_url,
            url_hash=self.url_hash,
            title=self.title,
            description=self.description,
            author=self.author,
            published_at=self.published_at,
            domain=self.domain,
            favicon_url=self.favicon_url,
            preview_markdown=self.preview_markdown,
            highlights=self.highlights,
            raw_payload=self.raw_payload,
            provider=self.provider,
            provider_result_id=self.provider_result_id,
            query_roles=list(self.query_roles),
            best_display_rank=self.best_rank,
            variant_count=self.variant_count,
        )
