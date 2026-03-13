from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.modules.search.sessions.dto import SearchCandidateDTO

HIGH_AUTHORITY_DOMAINS = (
    ".gov",
    ".edu",
    "arxiv.org",
    "nature.com",
    "science.org",
    "nih.gov",
    "nasa.gov",
    "who.int",
    "cdc.gov",
    "pubmed.ncbi.nlm.nih.gov",
)
PROFESSIONAL_DOMAINS = HIGH_AUTHORITY_DOMAINS + (
    "ieee.org",
    "acm.org",
    "github.com",
    "docs.",
)
LOW_CREDIBILITY_HINTS = (
    "clickbait",
    "you won't believe",
    "shocking",
    "viral",
)


@dataclass(slots=True)
class SearchQualitySnapshot:
    overall: float
    recency: float
    authority: float
    credibility: float
    professional: float
    freshness_satisfied: bool
    authority_hit: bool


def score_search_results(
    candidates: list[SearchCandidateDTO],
    *,
    freshness_hours: int | None,
    now: datetime | None = None,
) -> SearchQualitySnapshot:
    if not candidates:
        return SearchQualitySnapshot(
            overall=0.0,
            recency=0.0,
            authority=0.0,
            credibility=0.0,
            professional=0.0,
            freshness_satisfied=False,
            authority_hit=False,
        )

    runtime_now = now or datetime.now(UTC)
    top_candidates = candidates[: min(len(candidates), 5)]
    weighted_scores: list[tuple[float, float, float, float, float]] = []
    freshness_satisfied = False
    authority_hit = False

    for candidate in top_candidates:
        weight = 1 / max(candidate.display_rank, 1)
        recency_score = _score_recency(candidate, freshness_hours=freshness_hours, now=runtime_now)
        authority_score = _score_authority(candidate)
        credibility_score = _score_credibility(candidate)
        professional_score = _score_professional(candidate, authority_score=authority_score)
        overall_score = (
            recency_score * 0.2
            + authority_score * 0.3
            + credibility_score * 0.25
            + professional_score * 0.25
        )
        weighted_scores.append(
            (weight, overall_score, recency_score, authority_score, credibility_score, professional_score)
        )
        if freshness_hours is None or recency_score >= 0.8:
            freshness_satisfied = True
        if authority_score >= 0.85:
            authority_hit = True

    total_weight = sum(weight for weight, *_ in weighted_scores) or 1.0
    overall = sum(weight * overall for weight, overall, *_ in weighted_scores) / total_weight
    recency = sum(weight * recency for weight, _, recency, *_ in weighted_scores) / total_weight
    authority = sum(weight * authority for weight, _, _, authority, *_ in weighted_scores) / total_weight
    credibility = sum(weight * credibility for weight, _, _, _, credibility, _ in weighted_scores) / total_weight
    professional = sum(weight * professional for weight, _, _, _, _, professional in weighted_scores) / total_weight
    return SearchQualitySnapshot(
        overall=round(_clamp(overall), 4),
        recency=round(_clamp(recency), 4),
        authority=round(_clamp(authority), 4),
        credibility=round(_clamp(credibility), 4),
        professional=round(_clamp(professional), 4),
        freshness_satisfied=freshness_satisfied,
        authority_hit=authority_hit,
    )


def _score_recency(candidate: SearchCandidateDTO, *, freshness_hours: int | None, now: datetime) -> float:
    published_at = candidate.published_at
    if published_at is None:
        return 0.25

    age_hours = max((now - published_at.astimezone(UTC)).total_seconds() / 3600, 0.0)
    if freshness_hours is not None:
        if age_hours <= freshness_hours:
            return 1.0
        if age_hours <= freshness_hours * 3:
            return max(0.2, 1 - ((age_hours - freshness_hours) / max(freshness_hours * 2, 1)) * 0.8)
        return 0.1

    if age_hours <= 24:
        return 1.0
    if age_hours <= 72:
        return 0.85
    if age_hours <= 24 * 7:
        return 0.7
    if age_hours <= 24 * 30:
        return 0.5
    return 0.25


def _score_authority(candidate: SearchCandidateDTO) -> float:
    domain = (candidate.domain or "").lower()
    if not domain:
        return 0.2
    if any(domain.endswith(suffix) for suffix in (".gov", ".edu")):
        return 1.0
    if any(keyword in domain for keyword in HIGH_AUTHORITY_DOMAINS):
        return 0.9
    if domain.startswith("docs.") or ".docs." in domain:
        return 0.85
    if domain.startswith("en.wikipedia.org"):
        return 0.6
    return 0.45


def _score_credibility(candidate: SearchCandidateDTO) -> float:
    title = (candidate.title or "").strip()
    preview = (candidate.preview_markdown or "").strip()
    raw_url = (candidate.raw_url or "").lower()
    score = 0.2
    if raw_url.startswith("https://"):
        score += 0.2
    if candidate.author:
        score += 0.2
    if candidate.published_at is not None:
        score += 0.15
    if len(title) >= 16:
        score += 0.15
    if len(preview) >= 40:
        score += 0.1
    if candidate.domain:
        score += 0.1
    lowered = f"{title} {preview}".lower()
    if any(hint in lowered for hint in LOW_CREDIBILITY_HINTS):
        score -= 0.25
    return _clamp(score)


def _score_professional(candidate: SearchCandidateDTO, *, authority_score: float) -> float:
    domain = (candidate.domain or "").lower()
    score = 0.25 + authority_score * 0.4
    if any(keyword in domain for keyword in PROFESSIONAL_DOMAINS):
        score += 0.2
    if candidate.author:
        score += 0.1
    if candidate.preview_markdown and len(candidate.preview_markdown) >= 80:
        score += 0.05
    return _clamp(score)


def _clamp(value: float, *, min_value: float = 0.0, max_value: float = 1.0) -> float:
    return max(min_value, min(value, max_value))
