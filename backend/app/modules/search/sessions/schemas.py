"""Request / response Pydantic schemas for the search API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ── Request ────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["fast", "auto", "deep"] = "auto"
    maxResults: int = Field(default=10, ge=1, le=100)
    freshnessHours: int | None = Field(default=24, ge=0)


# ── Response ───────────────────────────────────────────────────────────────

class SearchCardView(BaseModel):
    """A single search result card shown to the user (ADR-001 §4.9)."""

    id: str
    title: str
    url: str
    sourceName: str
    sourceTypeBadge: str
    publishedAt: datetime | None = None
    authorityBadge: str | None = None
    whySelected: str
    highlights: list[str]
    importSuggestion: str
    description: str | None = None
    author: str | None = None
    displayRank: int = 0


class SearchSessionView(BaseModel):
    searchSessionId: str
    mode: str
    modeLabel: str
    status: str
    execution: str


class SearchResponse(BaseModel):
    item: SearchSessionView
    items: list[SearchCardView] = []
    message: str = ""
    meta: dict | None = None
