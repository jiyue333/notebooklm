from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class SearchCandidateDTO:
    provider_result_id: str | None
    raw_url: str
    canonical_url: str
    title: str
    description: str | None
    author: str | None = None
    published_at: datetime | None = None
    domain: str | None = None
    favicon_url: str | None = None
    display_rank: int = 0
    preview_markdown: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CreateSearchSessionInput:
    """service → repo 之间传递创建搜索会话所需的全部参数。"""

    user_id: str
    notebook_id: str
    query: str
    normalized_query: str
    mode: str
    execution_mode: str
    provider_name: str
    provider_request_json: dict[str, Any]
    status: str
    mode_label: str
    created_at: datetime
    expires_at: datetime
