"""Stage G – Coverage-Aware Slate Building.

Instead of a simple top-K sort, the slate builder allocates results
into *buckets* that mirror the coverage facets from the TaskSpec
(ADR-001 §4.8).  This guarantees the final slate has diverse
perspectives, not just the highest-scored near-duplicates.

Bucket quotas (approximate, shrink for fast mode):
  - overview / survey   : 2-4
  - primary / official   : 4-6
  - recent update        : 2-4
  - critique / limitation: 2-3
  - implementation / case: 2-3

After bucket allocation the builder generates a human-readable
``why_selected`` string and an ``import_suggestion`` for each card.
"""

from __future__ import annotations

from app.modules.search.pipeline.types import (
    AuthorityTier,
    CoverageFacet,
    DocType,
    ImportSuggestion,
    NotebookContext,
    QueryRole,
    ScoredCandidate,
    SearchCard,
    TaskSpec,
)

# ── bucket config ──────────────────────────────────────────────────────────

_ROLE_TO_FACET: dict[QueryRole, CoverageFacet] = {
    QueryRole.CANONICAL: CoverageFacet.OVERVIEW,
    QueryRole.TERMINOLOGY: CoverageFacet.OVERVIEW,
    QueryRole.PRIMARY: CoverageFacet.PRIMARY,
    QueryRole.RECENT: CoverageFacet.RECENT,
    QueryRole.CRITICAL: CoverageFacet.CRITIQUE,
    QueryRole.IMPLEMENTATION: CoverageFacet.IMPLEMENTATION,
    QueryRole.NOTEBOOK_GAP: CoverageFacet.OVERVIEW,
}

_BUCKET_QUOTAS_DEEP: dict[CoverageFacet, tuple[int, int]] = {
    CoverageFacet.OVERVIEW: (2, 4),
    CoverageFacet.PRIMARY: (4, 6),
    CoverageFacet.RECENT: (2, 4),
    CoverageFacet.CRITIQUE: (2, 3),
    CoverageFacet.IMPLEMENTATION: (2, 3),
}

_BUCKET_QUOTAS_FAST: dict[CoverageFacet, tuple[int, int]] = {
    CoverageFacet.OVERVIEW: (2, 3),
    CoverageFacet.PRIMARY: (2, 4),
    CoverageFacet.RECENT: (1, 2),
    CoverageFacet.CRITIQUE: (1, 2),
    CoverageFacet.IMPLEMENTATION: (1, 2),
}

_MAX_SLATE_FAST = 12
_MAX_SLATE_DEEP = 20

# ── public API ─────────────────────────────────────────────────────────────


def build_slate(
    scored: list[ScoredCandidate],
    task: TaskSpec,
    notebook: NotebookContext,
    search_mode: str,
    target_count: int | None = None,
) -> list[SearchCard]:
    """Select, annotate and order the final slate of search cards."""

    is_deep = search_mode == "deep"
    quotas = _BUCKET_QUOTAS_DEEP if is_deep else _BUCKET_QUOTAS_FAST
    mode_cap = _MAX_SLATE_DEEP if is_deep else _MAX_SLATE_FAST
    max_slate = min(mode_cap, max(1, target_count or mode_cap))
    existing_url_set = set(notebook.existing_article_urls)
    facet_order = list(dict.fromkeys([*task.coverage_facets, *quotas.keys()]))

    # 1. Bucket candidates by their primary coverage facet.
    buckets: dict[CoverageFacet, list[ScoredCandidate]] = {f: [] for f in CoverageFacet}
    for c in sorted(scored, key=lambda x: x.scores.final_score, reverse=True):
        facet = _primary_facet(c)
        buckets[facet].append(c)

    # 2. Fill each bucket up to its max quota.
    selected: list[tuple[ScoredCandidate, CoverageFacet]] = []
    selected_urls: set[str] = set()

    for facet in facet_order:
        _min, _max = quotas[facet]
        pool = buckets.get(facet, [])
        count = 0
        for c in pool:
            if count >= _max or len(selected) >= max_slate:
                break
            if c.canonical_url in selected_urls:
                continue
            selected.append((c, facet))
            selected_urls.add(c.canonical_url)
            count += 1

    # 3. If under max_slate, fill from remaining high-scoring candidates.
    if len(selected) < max_slate:
        all_sorted = sorted(scored, key=lambda x: x.scores.final_score, reverse=True)
        for c in all_sorted:
            if len(selected) >= max_slate:
                break
            if c.canonical_url in selected_urls:
                continue
            selected.append((c, _primary_facet(c)))
            selected_urls.add(c.canonical_url)

    # 4. Build SearchCard for each selection.
    cards: list[SearchCard] = []
    for rank, (c, facet) in enumerate(selected, start=1):
        cards.append(_to_card(c, facet, rank, existing_url_set))

    return cards


# ── card construction ──────────────────────────────────────────────────────

def _to_card(
    c: ScoredCandidate,
    facet: CoverageFacet,
    rank: int,
    existing_urls: set[str],
) -> SearchCard:
    return SearchCard(
        title=c.title,
        url=c.canonical_url,
        source_name=c.domain or "",
        source_type_badge=c.doc_type.value,
        published_at=c.published_at,
        authority_badge=_authority_badge(c.authority_tier),
        why_selected=_generate_why(c, facet),
        highlights=c.highlights[:2],
        import_suggestion=_import_suggestion(c, existing_urls),
        provider=c.provider,
        provider_result_id=c.provider_result_id,
        url_hash=c.url_hash,
        canonical_url=c.canonical_url,
        description=c.description,
        author=c.author,
        domain=c.domain,
        favicon_url=c.favicon_url,
        preview_markdown=c.preview_markdown,
        doc_type=c.doc_type,
        final_score=c.scores.final_score,
        display_rank=rank,
    )


def _authority_badge(tier: AuthorityTier) -> str | None:
    if tier == AuthorityTier.TIER1:
        return "权威来源"
    if tier == AuthorityTier.TIER2:
        return "知名来源"
    return None


def _import_suggestion(
    c: ScoredCandidate,
    existing_urls: set[str],
) -> ImportSuggestion:
    if c.canonical_url in existing_urls:
        return ImportSuggestion.DUPLICATE_RISK
    if c.scores.final_score >= 0.6:
        return ImportSuggestion.RECOMMENDED
    return ImportSuggestion.OPTIONAL


# ── why_selected generation ────────────────────────────────────────────────

_FACET_REASONS: dict[CoverageFacet, str] = {
    CoverageFacet.OVERVIEW: "提供主题概览",
    CoverageFacet.PRIMARY: "一手来源 / 官方资料",
    CoverageFacet.RECENT: "最近更新",
    CoverageFacet.CRITIQUE: "补充风险 / 局限性视角",
    CoverageFacet.IMPLEMENTATION: "实现方案 / 案例研究",
}

_DOC_TYPE_LABELS: dict[DocType, str] = {
    DocType.PAPER: "学术论文",
    DocType.REPORT: "研究报告",
    DocType.OFFICIAL: "官方文档",
    DocType.BLOG: "技术博客",
    DocType.NEWS: "新闻报道",
    DocType.PDF: "PDF 文档",
    DocType.WIKI: "百科",
}


def _generate_why(c: ScoredCandidate, facet: CoverageFacet) -> str:
    parts: list[str] = []

    facet_reason = _FACET_REASONS.get(facet)
    if facet_reason:
        parts.append(facet_reason)

    doc_label = _DOC_TYPE_LABELS.get(c.doc_type)
    if doc_label:
        parts.append(doc_label)

    if c.is_primary_source and "一手来源" not in (facet_reason or ""):
        parts.append("一手来源")

    if c.authority_tier == AuthorityTier.TIER1:
        parts.append("高权威来源")

    return "；".join(parts) if parts else "相关结果"


# ── facet assignment ───────────────────────────────────────────────────────

def _primary_facet(c: ScoredCandidate) -> CoverageFacet:
    """Determine the single best coverage facet for this candidate."""
    if c.query_roles:
        for role in c.query_roles:
            facet = _ROLE_TO_FACET.get(role)
            if facet is not None:
                return facet

    if c.doc_type in (DocType.PAPER, DocType.REPORT, DocType.OFFICIAL):
        return CoverageFacet.PRIMARY
    return CoverageFacet.OVERVIEW
