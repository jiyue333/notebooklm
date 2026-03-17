"""Data types for the ingest pipeline.

Each stage consumes and produces typed dataclasses so the pipeline
is easy to test, log, and evolve independently.

Pipeline stages:
  A  Fetch & Fingerprint   → FetchedArtifact
  B  Canonicalize & Dedup  → CanonicalDoc
  C  Document Type Router  → DocRoute
  D  Parse to Markdown     → FusedDocument  (MinerU / Dripper / text)
  E  TOC Generation        → list[TOCNode]
  F  BlockGraph            → BlockGraph
  G  Chunk & Embed         → list[ChunkDraft]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class InputType(str, Enum):
    URL = "url"
    FILE = "file"
    TEXT = "text"
    SEARCH_RESULT = "search_result"


@dataclass(slots=True)
class IngestInput:
    """What the caller hands to the pipeline."""

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


# ---------------------------------------------------------------------------
# Stage A – Fetch & Fingerprint
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class FetchedArtifact:
    raw_bytes: bytes
    content_hash: str  # SHA-256
    content_type: str  # MIME
    file_name: str | None = None
    file_ext: str | None = None
    source_url: str | None = None
    http_status: int | None = None
    http_headers: dict[str, str] = field(default_factory=dict)
    fetched_at: datetime | None = None
    size_bytes: int = 0
    raw_text: str | None = None


# ---------------------------------------------------------------------------
# Stage B – Canonicalize
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class CanonicalDoc:
    artifact: FetchedArtifact
    dedupe_key: str
    is_duplicate: bool = False
    duplicate_article_id: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    canonical_url: str | None = None


# ---------------------------------------------------------------------------
# Stage C – Document Type Routing
# ---------------------------------------------------------------------------

class DocCategory(str, Enum):
    HTML = "html"
    PDF = "pdf"
    OFFICE = "office"
    TEXT = "text"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class DocRoute:
    category: DocCategory
    mime_type: str
    file_ext: str | None = None
    parser_hints: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage D – Parse to Markdown (single parser per type)
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ParseCandidate:
    """Intermediate result from a single parser."""

    parser_name: str
    markdown: str
    title: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    description: str | None = None
    language: str | None = None
    word_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FusedDocument:
    """Final parsed document ready for downstream stages."""

    clean_markdown: str
    title: str
    author: str | None = None
    published_at: datetime | None = None
    description: str | None = None
    language: str | None = None
    word_count: int = 0
    quality_score: float = 0.0
    primary_parser: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage E – TOC Builder
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class TOCNode:
    id: str
    title: str
    level: int
    anchor: str
    is_synthetic: bool = False
    children: list[TOCNode] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Stage F – BlockGraph
# ---------------------------------------------------------------------------

class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    QUOTE = "quote"
    IMAGE = "image"
    EQUATION = "equation"
    FOOTNOTE = "footnote"
    CITATION = "citation"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class Block:
    block_id: str
    block_type: BlockType
    text: str
    section_id: str | None = None
    level: int = 0
    line_start: int = 0
    line_end: int = 0
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BlockEdge:
    source_id: str
    target_id: str
    relation: str  # "parent_of", "next", "refers_to", "cites"


@dataclass(slots=True)
class BlockGraph:
    blocks: list[Block] = field(default_factory=list)
    edges: list[BlockEdge] = field(default_factory=list)

    @property
    def block_type_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.blocks:
            counts[b.block_type.value] = counts.get(b.block_type.value, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Stage G – Indexer
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    text: str
    token_count: int = 0
    section_id: str | None = None
    embedding: list[float] | None = None


# ---------------------------------------------------------------------------
# Pipeline context & result
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class IngestContext:
    ingest_input: IngestInput
    existing_dedupe_keys: set[str] = field(default_factory=set)


@dataclass(slots=True)
class IngestResult:
    fused_doc: FusedDocument | None = None
    toc: list[TOCNode] = field(default_factory=list)
    block_graph: BlockGraph | None = None
    chunks: list[ChunkDraft] = field(default_factory=list)
    is_duplicate: bool = False
    duplicate_article_id: str | None = None
    doc_route: DocRoute | None = None
    primary_parser: str = ""
    quality_score: float = 0.0
    elapsed_stages: dict[str, float] = field(default_factory=dict)
