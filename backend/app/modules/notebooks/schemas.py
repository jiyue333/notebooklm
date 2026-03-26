from __future__ import annotations

from pydantic import BaseModel, Field


class NotebookCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    emoji: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = Field(default=None, max_length=8)


class NotebookUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    emoji: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = Field(default=None, max_length=8)


class ArticleUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
