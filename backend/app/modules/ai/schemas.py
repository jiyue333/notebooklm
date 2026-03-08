from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversationId: str | None = None
    articleId: str | None = None
    message: str = Field(min_length=1)
