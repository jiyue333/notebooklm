"""Ingest pipeline 全部数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ── 输入 ──────────────────────────────────────────────────────────────

class InputType(str, Enum):
    URL = "url"
    FILE = "file"
    TEXT = "text"
    SEARCH_RESULT = "search_result"


@dataclass(slots=True)
class IngestInput:
    input_type: InputType
    notebook_id: str
    user_id: str
    title: str = ""
    source_url: str | None = None
    file_bytes: bytes | None = None
    file_name: str | None = None
    file_mime: str | None = None
    raw_text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    description: str | None = None


# ── Phase 1 接入层 ────────────────────────────────────────────────────

class DocRoute(str, Enum):
    PDF = "pdf"
    OFFICE = "office"
    IMAGE = "image"
    HTML = "html"
    TEXT = "text"


@dataclass(slots=True)
class TikaMetadata:
    mime_type: str = "application/octet-stream"
    language: str | None = None
    title: str | None = None
    author: str | None = None
    page_count: int | None = None


@dataclass(slots=True)
class FetchedContent:
    raw_bytes: bytes
    content_hash: str
    tika: TikaMetadata
    route: DocRoute
    source_url: str | None = None
    file_name: str | None = None


# ── Phase 3 规范化层 ──────────────────────────────────────────────────

@dataclass(slots=True)
class TOCNode:
    id: str
    title: str
    level: int
    anchor: str


@dataclass(slots=True)
class RemarkResult:
    mdast: dict[str, Any]
    clean_markdown: str
    html: str
    toc: list[TOCNode]
    reading_time_minutes: int
    reading_time_words: int
    fixes_applied: int


# ── Phase 4 索引层 ────────────────────────────────────────────────────

@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    text: str
    token_count: int = 0
    section_id: str | None = None
    heading_title: str | None = None
    contextualized_text: str | None = None
    embedding: list[float] | None = None


# ── Pipeline 结果 ─────────────────────────────────────────────────────

@dataclass(slots=True)
class IngestResult:
    clean_markdown: str | None = None
    content_html: str | None = None
    mdast_json: dict[str, Any] | None = None
    toc: list[TOCNode] = field(default_factory=list)
    chunks: list[ChunkDraft] = field(default_factory=list)
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    reading_time_minutes: int | None = None
    parser_name: str = ""
    content_hash: str = ""
    tika_mime: str | None = None
    is_duplicate: bool = False
    duplicate_article_id: str | None = None
    elapsed_stages: dict[str, float] = field(default_factory=dict)
