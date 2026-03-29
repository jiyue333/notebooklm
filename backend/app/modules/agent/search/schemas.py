"""搜索 API 请求 / 响应 Pydantic schemas。"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.modules.agent.search.state import SearchResponsePayload

_QUERY_MAX_LENGTH = 512
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?"
)
_PROMPT_INJECTION_PATTERN = re.compile(
    r"(?i)(ignore\s+previous\s+instructions|system\s+prompt|developer\s+message|越权|忽略之前指令)"
)


def _normalize_query(value: str) -> str:
    sanitized = value.replace("\x00", " ").strip()
    return re.sub(r"\s+", " ", sanitized)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4096)
    mode: Literal["fast", "auto", "deep"] = "auto"
    maxResults: int = Field(default=10, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = _normalize_query(value)
        if not normalized:
            raise ValueError("query 不能为空")
        if len(normalized) > _QUERY_MAX_LENGTH:
            raise ValueError(f"query 长度不能超过 {_QUERY_MAX_LENGTH} 个字符")
        if _SECRET_PATTERN.search(normalized):
            raise ValueError("query 中包含疑似敏感凭据，请移除后重试")
        if _PROMPT_INJECTION_PATTERN.search(normalized):
            raise ValueError("query 包含异常指令片段，请改为明确的检索问题")
        return normalized


class SearchResponse(SearchResponsePayload):
    pass
