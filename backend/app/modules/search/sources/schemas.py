from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ManualSourceRequest(BaseModel):
    sourceType: Literal["web", "text"]
    url: str | None = None
    title: str | None = Field(default=None, max_length=255)
    content: str | None = None

