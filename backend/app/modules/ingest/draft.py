from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class IngestDraft:
    input_type: str
    title: str
    preview_markdown: str | None = None
    source_url: str | None = None
    normalized_url: str | None = None
    raw_text_input: str | None = None
    file_name: str | None = None
    file_mime: str | None = None
    file_bytes: bytes | None = None
    origin_search_session_id: str | None = None
    origin_search_result_id: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    source_title_raw: str | None = None
