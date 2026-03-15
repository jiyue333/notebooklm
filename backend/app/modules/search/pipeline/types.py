"""Data types for the ADR-001 search pipeline.

Every stage consumes and produces typed dataclasses so the pipeline
is easy to test, log, and evolve independently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Stage A – Task Parsing
# ---------------------------------------------------------------------------

class SearchIntent(str, Enum):
    EXPLORE = "explore"
    COMPARE = "compare"
    ANSWER = "answer"
    LITERATURE_REVIEW = "literature_review"
    FIND_PRIMARY_SOURCE = "find_primary_source"


class TimeSensitivity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CoverageFacet(str, Enum):
    OVERVIEW = "overview"
    RECENT = "recent"
    PRIMARY = "primary"
    CRITIQUE = "critique"
    IMPLEMENTATION = "implementation"


class SourceMix(str, Enum):
    WEB = "web"
    PAPER = "paper"
    PDF = "pdf"
    OFFICIAL_DOC = "official_doc"


@dataclass(slots=True)
class TaskSpec:
    intent: SearchIntent
    domain: str
    time_sensitivity: TimeSensitivity
    expected_source_mix: list[SourceMix]
    coverage_facets: list[CoverageFacet]
    primary_source_preference: TimeSensitivity  # reuse enum: high/medium/low
    notebook_novelty_requirement: TimeSensitivity


# ---------------------------------------------------------------------------
# Stage B – Query Lattice
# ---------------------------------------------------------------------------

class QueryRole(str, Enum):
    CANONICAL = "canonical"
    TERMINOLOGY = "terminology"
    PRIMARY = "primary"
    RECENT = "recent"
    CRITICAL = "critical"
    IMPLEMENTATION = "implementation"
    NOTEBOOK_GAP = "notebook_gap"


@dataclass(slots=True)
class QueryFamily:
    role: QueryRole
    query_text: str
    max_results: int = 10
    freshness_hours: int | None = None


# ---------------------------------------------------------------------------
# Stage C – Recall
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class RawCandidate:
    """A single result coming back from a search provider."""

    provider: str
    provider_result_id: str | None
    raw_url: str
    canonical_url: str
    title: str
    description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    domain: str | None = None
    favicon_url: str | None = None
    preview_markdown: str | None = None
    highlights: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    query_role: QueryRole = QueryRole.CANONICAL
    display_rank: int = 0


# ---------------------------------------------------------------------------
# Stage D – Canonicalize
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CanonicalCandidate:
    """Merged, de-duplicated candidate with the best variant chosen."""

    canonical_url: str
    url_hash: str
    title: str
    description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    domain: str | None = None
    favicon_url: str | None = None
    preview_markdown: str | None = None
    highlights: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    provider: str = "exa"
    provider_result_id: str | None = None
    query_roles: list[QueryRole] = field(default_factory=list)
    best_display_rank: int = 0
    variant_count: int = 1


# ---------------------------------------------------------------------------
# Stage E – Enrichment
# ---------------------------------------------------------------------------

class DocType(str, Enum):
    PAPER = "paper"
    REPORT = "report"
    BLOG = "blog"
    OFFICIAL = "official"
    NEWS = "news"
    PDF = "pdf"
    WIKI = "wiki"
    OTHER = "other"


class AuthorityTier(str, Enum):
    TIER1 = "tier1"  # .gov, .edu, top journals, arxiv
    TIER2 = "tier2"  # well-known engineering blogs, docs sites
    TIER3 = "tier3"  # everything else


@dataclass(slots=True)
class EnrichedCandidate:
    canonical_url: str
    url_hash: str
    title: str
    description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    domain: str | None = None
    favicon_url: str | None = None
    preview_markdown: str | None = None
    highlights: list[str] = field(default_factory=list)
    raw_payload: dict[str, Any] = field(default_factory=dict)
    provider: str = "exa"
    provider_result_id: str | None = None
    query_roles: list[QueryRole] = field(default_factory=list)
    best_display_rank: int = 0
    variant_count: int = 1
    # enrichment fields
    doc_type: DocType = DocType.OTHER
    authority_tier: AuthorityTier = AuthorityTier.TIER3
    is_primary_source: bool = False
    ingestability_score: float = 0.5


# ---------------------------------------------------------------------------
# Stage F – Scoring
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ScoreBreakdown:
    topical_relevance: float = 0.0
    authority: float = 0.0
    credibility: float = 0.0
    professional_depth: float = 0.0
    recency_fit: float = 0.0
    novelty_to_notebook: float = 0.0
    ingestability: float = 0.0
    diversity_gain: float = 0.0
    final_score: float = 0.0


@dataclass(slots=True)
class ScoredCandidate:
    canonical_url: str
    url_hash: str
    title: str
    description: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    domain: str | None = None
    favicon_url: str | None = None
    preview_markdown: str | None = None
    highlights: list[str] = field(default_factory=list)
    provider: str = "exa"
    provider_result_id: str | None = None
    query_roles: list[QueryRole] = field(default_factory=list)
    doc_type: DocType = DocType.OTHER
    authority_tier: AuthorityTier = AuthorityTier.TIER3
    is_primary_source: bool = False
    ingestability_score: float = 0.5
    scores: ScoreBreakdown = field(default_factory=ScoreBreakdown)


# ---------------------------------------------------------------------------
# Stage G – Slate Building (final output)
# ---------------------------------------------------------------------------

class ImportSuggestion(str, Enum):
    RECOMMENDED = "recommended"
    OPTIONAL = "optional"
    DUPLICATE_RISK = "duplicate_risk"


@dataclass(slots=True)
class SearchCard:
    """The final user-facing search result card per ADR-001 §4.9."""

    title: str
    url: str
    source_name: str
    source_type_badge: str  # "paper" | "report" | "official" | "blog" | "pdf" | ...
    published_at: datetime | None
    authority_badge: str | None
    why_selected: str
    highlights: list[str]
    import_suggestion: ImportSuggestion
    # internal identifiers for persistence
    provider: str = "exa"
    provider_result_id: str | None = None
    url_hash: str = ""
    canonical_url: str = ""
    description: str | None = None
    author: str | None = None
    domain: str | None = None
    favicon_url: str | None = None
    preview_markdown: str | None = None
    doc_type: DocType = DocType.OTHER
    final_score: float = 0.0
    display_rank: int = 0


# ---------------------------------------------------------------------------
# Pipeline context & result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class NotebookContext:
    notebook_id: str
    notebook_title: str
    existing_article_urls: list[str] = field(default_factory=list)
    existing_article_titles: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineContext:
    user_query: str
    search_mode: str  # "fast" | "deep"
    notebook: NotebookContext
    exa_api_key: str
    max_results: int = 10
    freshness_hours: int | None = 24


@dataclass(slots=True)
class PipelineResult:
    cards: list[SearchCard]
    task_spec: TaskSpec
    query_families: list[QueryFamily]
    raw_candidate_count: int = 0
    canonical_candidate_count: int = 0
    enriched_candidate_count: int = 0
    elapsed_stages: dict[str, float] = field(default_factory=dict)
