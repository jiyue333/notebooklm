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
