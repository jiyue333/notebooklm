"""Data types for the ADR-003 summary pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Stage A – Article Profiling
# ---------------------------------------------------------------------------

class ArticleType(str, Enum):
    PAPER = "paper"
    REPORT = "report"
    BLOG = "blog"
    TUTORIAL = "tutorial"
    NEWS = "news"
    DOCS = "docs"
    UNKNOWN = "unknown"


class EvidenceStyle(str, Enum):
    QUANTITATIVE = "quantitative"
    QUALITATIVE = "qualitative"
    MIXED = "mixed"


class StructureQuality(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SectionRole(str, Enum):
    BACKGROUND = "background"
    PROBLEM = "problem"
    METHOD = "method"
    RESULT = "result"
    LIMITATION = "limitation"
    IMPLICATION = "implication"
    HOW_TO = "how_to"
    OPINION = "opinion"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ArticleProfile:
    article_type: ArticleType
    evidence_style: EvidenceStyle
    structure_quality: StructureQuality
    domain: str
    section_roles: dict[str, SectionRole] = field(default_factory=dict)
    important_entities: list[str] = field(default_factory=list)
    word_count: int = 0


# ---------------------------------------------------------------------------
# Stage B – Evidence Skeleton
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EvidenceBullet:
    text: str
    role: SectionRole
    block_ids: list[str] = field(default_factory=list)
    salience_score: float = 0.0


# ---------------------------------------------------------------------------
# Stage C – Route Selection
# ---------------------------------------------------------------------------

class SummaryRoute(str, Enum):
    S = "S"  # short / high structure → direct
    M = "M"  # medium → section micro-summary + merge
    L = "L"  # long → hierarchical
    X = "X"  # poor parse → conservative


# ---------------------------------------------------------------------------
# Stage D – Candidate Generation + Judge
# ---------------------------------------------------------------------------

class CandidateStyle(str, Enum):
    CLAIM_FIRST = "claim_first"
    CONTRIBUTION_FIRST = "contribution_first"
    READER_FIRST = "reader_first"


@dataclass(slots=True)
class SummaryCandidate:
    style: CandidateStyle
    text: str
    evidence_bullet_ids: list[int] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class JudgeScoreBreakdown:
    fidelity: float = 0.0
    coverage: float = 0.0
    clarity: float = 0.0
    concision: float = 0.0
    total: float = 0.0


@dataclass(slots=True)
class ScoredSummaryCandidate:
    candidate: SummaryCandidate
    scores: JudgeScoreBreakdown
    rank: int = 0


# ---------------------------------------------------------------------------
# Stage E – Final Output
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EvidenceSpan:
    bullet_text: str
    block_ids: list[str] = field(default_factory=list)
    role: str = ""


@dataclass(slots=True)
class ArticleSummary:
    summary_text: str
    summary_type: str = "canonical"
    evidence_spans: list[EvidenceSpan] = field(default_factory=list)
    profile_tags: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    prompt_version: str = ""
    route: SummaryRoute = SummaryRoute.S


# ---------------------------------------------------------------------------
# Pipeline context & result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class SummaryInput:
    article_id: str
    notebook_id: str
    user_id: str
    title: str
    clean_markdown: str
    toc_json: list[dict] = field(default_factory=list)
    block_graph_json: dict | None = None
    quality_profile_json: dict | None = None
    quality_score: float = 0.0
    content_hash: str = ""
    language: str = "auto"


@dataclass(slots=True)
class SummaryContext:
    summary_input: SummaryInput


@dataclass(slots=True)
class SummaryResult:
    summary: ArticleSummary | None = None
    profile: ArticleProfile | None = None
    route: SummaryRoute = SummaryRoute.S
    evidence_count: int = 0
    candidate_count: int = 0
    cache_hit: bool = False
    elapsed_stages: dict[str, float] = field(default_factory=dict)
