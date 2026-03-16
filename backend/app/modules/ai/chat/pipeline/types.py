"""Data types for the ADR-004 chat pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Stage A – Scope Router
# ---------------------------------------------------------------------------

class ChatRoute(str, Enum):
    ARTICLE_GROUNDED = "article_grounded"
    GENERAL = "general"
    RECOMMENDATION = "recommendation"
    NOTEBOOK_RESEARCH = "notebook_research"
    AMBIGUOUS = "ambiguous"


@dataclass(slots=True)
class RouteDecision:
    route: ChatRoute
    confidence: float = 1.0
    reason: str = ""
    shadow_route: ChatRoute | None = None


# ---------------------------------------------------------------------------
# Stage B – Retrieval
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class EvidenceChunk:
    """A retrieved block/section snippet with provenance."""

    article_id: str
    chunk_id: str | None = None
    section_id: str | None = None
    text: str = ""
    score: float = 0.0
    matched_by: str = ""  # "semantic" | "lexical" | "rrf"


@dataclass(slots=True)
class RecommendedArticle:
    article_id: str
    title: str
    notebook_id: str
    score: float = 0.0
    why_similar: str = ""
    snippet: str = ""


@dataclass(slots=True)
class EvidenceCluster:
    """A group of evidence chunks around a sub-topic (notebook_research)."""

    label: str
    chunks: list[EvidenceChunk] = field(default_factory=list)
    article_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalResult:
    route: ChatRoute
    evidence_chunks: list[EvidenceChunk] = field(default_factory=list)
    recommended_articles: list[RecommendedArticle] = field(default_factory=list)
    evidence_clusters: list[EvidenceCluster] = field(default_factory=list)
    article_shortlist_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage C – Composer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class DraftAnswer:
    route: ChatRoute
    answer_text: str = ""
    evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    related_articles: list[dict[str, Any]] = field(default_factory=list)
    route_badge: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage D – Verifier
# ---------------------------------------------------------------------------

class FallbackReason(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOW_SIMILARITY = "low_similarity"
    EVIDENCE_CONFLICT = "evidence_conflict"
    UNSTABLE_ROUTE = "unstable_route"
    NONE = "none"


@dataclass(slots=True)
class VerifiedAnswer:
    answer: DraftAnswer
    is_verified: bool = True
    fallback_used: bool = False
    fallback_reason: FallbackReason = FallbackReason.NONE
    evidence_coverage: float = 0.0
    confidence: float = 0.0


# ---------------------------------------------------------------------------
# Pipeline context & result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ReadingCursor:
    page: int | None = None
    section_id: str | None = None
    block_id: str | None = None


@dataclass(slots=True)
class ChatInput:
    question: str
    user_id: str
    notebook_id: str
    article_id: str | None = None
    conversation_id: str | None = None
    reading_cursor: ReadingCursor | None = None
    recent_highlights: list[str] = field(default_factory=list)
    recent_turns: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class ChatContext:
    chat_input: ChatInput
    user: object = None  # for LLM calls (GENERAL route)


@dataclass(slots=True)
class ChatResult:
    route: ChatRoute = ChatRoute.GENERAL
    answer_text: str = ""
    evidence_spans: list[dict[str, Any]] = field(default_factory=list)
    related_articles: list[dict[str, Any]] = field(default_factory=list)
    route_badge: str = ""
    confidence: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    conversation_id: str | None = None
    message_id: str | None = None
    elapsed_stages: dict[str, float] = field(default_factory=dict)
