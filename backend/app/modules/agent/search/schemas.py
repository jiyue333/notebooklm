"""搜索 API 请求 / 响应 Pydantic schemas。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.modules.agent.search.state import SearchResponsePayload


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Literal["fast", "auto", "deep"] = "auto"
    maxResults: int = Field(default=10, ge=1, le=10)


class SearchResponse(SearchResponsePayload):
    pass
