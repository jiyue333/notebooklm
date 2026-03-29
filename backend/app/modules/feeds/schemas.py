from __future__ import annotations

from pydantic import BaseModel, Field


class FeedDiscoverRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class FeedCreateRequest(BaseModel):
    feedUrl: str = Field(min_length=1, max_length=2048)
    categoryName: str | None = Field(default=None, max_length=128)


class FeedCategoryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    hideGlobally: bool | None = False


class FeedEntriesStatusUpdateRequest(BaseModel):
    entryIds: list[int] = Field(min_length=1)
    status: str = Field(default="read", max_length=16)


class FeedDigestDateRequest(BaseModel):
    date: str = Field(min_length=8, max_length=10)
