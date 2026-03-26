from __future__ import annotations

from pydantic import BaseModel, Field


class NoteUpsertRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    content: str | None = None
    type: str | None = Field(default=None, max_length=64)
    sources: int | None = Field(default=None, ge=0)
    tags: list[str] | None = None
