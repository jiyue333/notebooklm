from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchSourcesRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["fast", "auto", "deep"] = "auto"
    maxResults: int = Field(default=10, ge=1, le=100)
    freshnessHours: int | None = Field(default=24, ge=0)
