from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class HighlightCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    color: str | None = Field(default=None, max_length=24)
    comment: str | None = Field(default=None, max_length=2000)
    startOffset: int | None = Field(default=None, ge=0)
    endOffset: int | None = Field(default=None, ge=0)
    occurrenceIndex: int | None = Field(default=None, ge=0)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.replace("\x00", " ").strip()
        if not normalized:
            raise ValueError("text 不能为空")
        return normalized


class HighlightUpdateRequest(BaseModel):
    color: str | None = Field(default=None, max_length=24)
    comment: str | None = Field(default=None, max_length=2000)

