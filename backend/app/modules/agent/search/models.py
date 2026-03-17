"""Pydantic models for the agent search pipeline structured outputs."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── Intent Recognition (chat model) ────────────────────────────────────────

class SearchIntent(str, Enum):
    EXPLORE = "explore"
    COMPARE = "compare"
    ANSWER = "answer"
    LITERATURE_REVIEW = "literature_review"
    FIND_PRIMARY_SOURCE = "find_primary_source"


class CoverageFacet(str, Enum):
    NOVELTY = "novelty"
    AUTHORITATIVE = "authoritative"
    OVERVIEW = "overview"
    RECENT = "recent"
    CRITIQUE = "critique"
    IMPLEMENTATION = "implementation"
    PRIMARY = "primary"


class IntentAnalysis(BaseModel):
    """Output of the intent-recognition step (chat model)."""

    intent: SearchIntent = Field(description="Primary search intent")
    domain: str = Field(description="Subject domain, e.g. cs, biomed, policy, general")
    facet_weights: dict[CoverageFacet, float] = Field(
        description="Weight for each coverage facet (0.0-1.0), higher = more important",
    )
    reformulated_queries: list[str] = Field(
        description="2-6 reformulated queries targeting different facets",
        min_length=1,
        max_length=8,
    )
    time_sensitive: bool = Field(
        default=False,
        description="Whether the query demands very recent results",
    )


# ── Search Result Item (from tools) ────────────────────────────────────────

class RawSearchItem(BaseModel):
    """A single result from any search tool, normalised."""

    title: str
    url: str
    description: str = ""
    author: str | None = None
    published_date: str | None = None
    highlights: list[str] = Field(default_factory=list)
    source_tool: str = ""


# ── Scoring & Ranking (lite model) ─────────────────────────────────────────

class ScoredItem(BaseModel):
    """A search result after LLM scoring."""

    title: str
    url: str
    description: str = ""
    author: str | None = None
    published_date: str | None = None
    highlights: list[str] = Field(default_factory=list)
    source_tool: str = ""
    relevance_score: float = Field(0.0, description="0-1 relevance to the query")
    authority_score: float = Field(0.0, description="0-1 source authority")
    novelty_score: float = Field(0.0, description="0-1 novelty vs existing notebook articles")
    final_score: float = Field(0.0, description="Weighted composite score")
    why_selected: str = Field("", description="Brief reason this result is valuable")


class ScoringOutput(BaseModel):
    """Batch scoring result from the lite model."""

    scored_items: list[ScoredItem]


# ── Final Search Card ──────────────────────────────────────────────────────

class SearchCardOut(BaseModel):
    """The final card sent to the frontend."""

    title: str
    url: str
    source_name: str = ""
    source_type_badge: str = ""
    published_at: str | None = None
    authority_badge: str | None = None
    why_selected: str = ""
    highlights: list[str] = Field(default_factory=list)
    import_suggestion: str = "optional"
    description: str = ""
    author: str | None = None
    final_score: float = 0.0
    display_rank: int = 0
