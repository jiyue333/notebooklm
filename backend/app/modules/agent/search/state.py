"""搜索图状态与结构化契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class SearchQueryPlan(BaseModel):
    key: str
    query: str
    intent: str = ""
    exclude_domains: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)


class SearchTaskSpec(BaseModel):
    search_type: str = "exploratory"
    content_depth: str = "mixed"
    time_sensitivity: str = "medium"
    authority_preference: str = "high"
    novelty_requirement: str = "medium"
    domain_hint: str = "general"
    rewritten_query: str
    query_plans: list[SearchQueryPlan] = Field(default_factory=list)
    score_weights: dict[str, float] = Field(default_factory=dict)


class SearchCandidate(BaseModel):
    title: str
    url: str
    domain: str
    description: str = ""
    author: str | None = None
    published_at: datetime | None = None
    highlights: list[str] = Field(default_factory=list)
    provider: str
    query_key: str = ""
    preferred_site_hit: bool = False
    recall_round: int = 1
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    final_score: float = 0.0
    why_selected: str = ""
    selected_reason_tags: list[str] = Field(default_factory=list)
    duplicate_risk: bool = False


class SearchRunView(BaseModel):
    id: str
    notebookId: str
    query: str
    mode: str
    modeLabel: str
    status: str
    currentRound: int = 1
    maxRounds: int = 1
    targetCount: int = 10
    elapsedMs: float = 0


class SearchResultCardView(BaseModel):
    id: str
    title: str
    url: str
    domain: str
    sourceName: str
    sourceTypeBadge: str
    authorityBadge: str | None = None
    publishedAt: datetime | None = None
    description: str = ""
    author: str | None = None
    highlights: list[str] = Field(default_factory=list)
    whySelected: str = ""
    importSuggestion: str = "optional"
    finalScore: float = 0.0
    scoreBreakdown: dict[str, float] = Field(default_factory=dict)
    provider: str
    queryFamily: str = ""
    preferredSiteHit: bool = False
    matchedPreferredSite: str | None = None
    duplicateRisk: bool = False
    selectedReasonTags: list[str] = Field(default_factory=list)
    faviconUrl: str | None = None
    displayRank: int = 0


class SearchResponsePayload(BaseModel):
    run: SearchRunView
    taskSpec: dict[str, Any] = Field(default_factory=dict)
    recallSummary: dict[str, Any] = Field(default_factory=dict)
    items: list[SearchResultCardView] = Field(default_factory=list)
    preferencesApplied: dict[str, Any] = Field(default_factory=dict)
    debug: dict[str, Any] | None = None


class SearchGraphState(TypedDict, total=False):
    query: str
    notebook_id: str
    notebook_title: str
    mode: str
    max_results: int
    target_count: int
    max_rounds: int
    current_round: int
    existing_article_urls: list[str]
    notebook_article_summaries: list[dict[str, str]]
    preferred_sites: list[str]
    exa_api_key: str | None
    tavily_api_key: str | None
    task_spec: SearchTaskSpec
    recall_candidates: list[SearchCandidate]
    selected_candidates: list[SearchCandidate]
    seen_urls: list[str]
    recall_summary: dict[str, Any]
    provider_call_budget: int
    provider_calls_used: int
    provider_call_counts: dict[str, int]
    tavily_disabled: bool
    tavily_disable_reason: str
    forced_include_domains: list[str]
    debug: dict[str, Any]
