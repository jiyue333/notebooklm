"""Stage F – Multi-Objective Scoring.

Implements the composite scoring formula from ADR-001 §4.7:

    final_score =
        0.32 * topical_relevance
      + 0.16 * authority
      + 0.12 * credibility
      + 0.10 * professional_depth
      + 0.10 * recency_fit
      + 0.08 * novelty_to_notebook
      + 0.07 * ingestability
      + 0.05 * diversity_gain

Each dimension is scored 0.0-1.0.  The scorer does NOT reorder
candidates – that's the slate builder's job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.search.pipeline.types import (
    AuthorityTier,
    DocType,
    EnrichedCandidate,
    NotebookContext,
    QueryRole,
    ScoreBreakdown,
    ScoredCandidate,
    TaskSpec,
    TimeSensitivity,
)

_WEIGHTS = {
    "topical_relevance": 0.32,
    "authority": 0.16,
    "credibility": 0.12,
    "professional_depth": 0.10,
    "recency_fit": 0.10,
    "novelty_to_notebook": 0.08,
    "ingestability": 0.07,
    "diversity_gain": 0.05,
}

_LOW_CREDIBILITY_HINTS = frozenset({
    "clickbait", "you won't believe", "shocking", "viral",
    "标题党", "震惊", "万万没想到",
})


def score(
    candidates: list[EnrichedCandidate],
    task: TaskSpec,
    notebook: NotebookContext,
    *,
    now: datetime | None = None,
) -> list[ScoredCandidate]:
    """Score every candidate and return ``ScoredCandidate`` list (unsorted)."""

    runtime_now = now or datetime.now(UTC)
    existing_url_set = set(notebook.existing_article_urls)
    existing_title_tokens = _tokenize_many(notebook.existing_article_titles)
    seen_domains: set[str] = set()

    results: list[ScoredCandidate] = []
    for c in candidates:
        breakdown = _score_one(
            c,
            task=task,
            now=runtime_now,
            existing_urls=existing_url_set,
            existing_title_tokens=existing_title_tokens,
            seen_domains=seen_domains,
        )
        seen_domains.add((c.domain or "").lower())
        results.append(_to_scored(c, breakdown))

    return results


# ── per-candidate scoring ──────────────────────────────────────────────────

def _score_one(
    c: EnrichedCandidate,
    *,
    task: TaskSpec,
    now: datetime,
    existing_urls: set[str],
    existing_title_tokens: set[str],
    seen_domains: set[str],
) -> ScoreBreakdown:
    topical = _topical_relevance(c)
    auth = _authority(c)
    cred = _credibility(c)
    depth = _professional_depth(c, auth)
    recency = _recency_fit(c, task, now)
    novelty = _novelty_to_notebook(c, existing_urls, existing_title_tokens)
    ingest = c.ingestability_score
    diversity = _diversity_gain(c, seen_domains)

    final = (
        _WEIGHTS["topical_relevance"] * topical
        + _WEIGHTS["authority"] * auth
        + _WEIGHTS["credibility"] * cred
        + _WEIGHTS["professional_depth"] * depth
        + _WEIGHTS["recency_fit"] * recency
        + _WEIGHTS["novelty_to_notebook"] * novelty
        + _WEIGHTS["ingestability"] * ingest
        + _WEIGHTS["diversity_gain"] * diversity
    )

    return ScoreBreakdown(
        topical_relevance=round(topical, 4),
        authority=round(auth, 4),
        credibility=round(cred, 4),
        professional_depth=round(depth, 4),
        recency_fit=round(recency, 4),
        novelty_to_notebook=round(novelty, 4),
        ingestability=round(ingest, 4),
        diversity_gain=round(diversity, 4),
        final_score=round(_clamp(final), 4),
    )


# ── dimension scorers ──────────────────────────────────────────────────────

def _topical_relevance(c: EnrichedCandidate) -> float:
    """Proxy: provider rank + whether multiple query roles matched."""
    rank_signal = max(0.0, 1.0 - (c.best_display_rank - 1) * 0.06)
    role_bonus = min(len(c.query_roles) * 0.1, 0.3)
    highlight_bonus = 0.1 if c.highlights else 0.0
    return _clamp(rank_signal + role_bonus + highlight_bonus)


def _authority(c: EnrichedCandidate) -> float:
    if c.authority_tier == AuthorityTier.TIER1:
        return 1.0
    if c.authority_tier == AuthorityTier.TIER2:
        return 0.7
    return 0.35


def _credibility(c: EnrichedCandidate) -> float:
    score = 0.2
    if c.canonical_url.startswith("https://"):
        score += 0.15
    if c.author:
        score += 0.2
    if c.published_at is not None:
        score += 0.15
    if c.title and len(c.title) >= 16:
        score += 0.1
    if c.preview_markdown and len(c.preview_markdown) >= 40:
        score += 0.1
    if c.domain:
        score += 0.1

    text = f"{c.title or ''} {c.preview_markdown or ''}".lower()
    if any(hint in text for hint in _LOW_CREDIBILITY_HINTS):
        score -= 0.25

    return _clamp(score)


def _professional_depth(c: EnrichedCandidate, authority_score: float) -> float:
    score = 0.2 + authority_score * 0.35
    if c.doc_type in (DocType.PAPER, DocType.REPORT, DocType.OFFICIAL):
        score += 0.2
    if c.author:
        score += 0.1
    if c.preview_markdown and len(c.preview_markdown) >= 100:
        score += 0.1
    if c.is_primary_source:
        score += 0.05
    return _clamp(score)


def _recency_fit(
    c: EnrichedCandidate,
    task: TaskSpec,
    now: datetime,
) -> float:
    if c.published_at is None:
        return 0.3

    age_hours = max((now - c.published_at.astimezone(UTC)).total_seconds() / 3600, 0.0)

    if task.time_sensitivity == TimeSensitivity.HIGH:
        if age_hours <= 72:
            return 1.0
        if age_hours <= 168:
            return 0.7
        if age_hours <= 720:
            return 0.4
        return 0.15
    elif task.time_sensitivity == TimeSensitivity.MEDIUM:
        if age_hours <= 168:
            return 1.0
        if age_hours <= 720:
            return 0.7
        if age_hours <= 4320:
            return 0.5
        return 0.25
    else:
        # low sensitivity – age barely matters
        if age_hours <= 8760:
            return 0.8
        return 0.5


def _novelty_to_notebook(
    c: EnrichedCandidate,
    existing_urls: set[str],
    existing_title_tokens: set[str],
) -> float:
    if c.canonical_url in existing_urls:
        return 0.0

    if existing_title_tokens:
        c_tokens = _tokenize(c.title)
        overlap = len(c_tokens & existing_title_tokens)
        if c_tokens and overlap / len(c_tokens) > 0.6:
            return 0.2
    return 1.0


def _diversity_gain(c: EnrichedCandidate, seen_domains: set[str]) -> float:
    domain = (c.domain or "").lower()
    if not domain:
        return 0.5
    if domain not in seen_domains:
        return 1.0
    return 0.3


# ── helpers ────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(v, hi))


def _tokenize(text: str) -> set[str]:
    import re
    return set(re.findall(r"\w+", text.lower()))


def _tokenize_many(texts: list[str]) -> set[str]:
    tokens: set[str] = set()
    for t in texts:
        tokens.update(_tokenize(t))
    return tokens


def _to_scored(c: EnrichedCandidate, breakdown: ScoreBreakdown) -> ScoredCandidate:
    return ScoredCandidate(
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
        provider=c.provider,
        provider_result_id=c.provider_result_id,
        query_roles=c.query_roles,
        doc_type=c.doc_type,
        authority_tier=c.authority_tier,
        is_primary_source=c.is_primary_source,
        ingestability_score=c.ingestability_score,
        scores=breakdown,
    )
