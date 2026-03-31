"""Phase 4 — 索引层：分块 + 向量化。"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import structlog
import nltk

from app.core.config import get_settings
from app.modules.ingest.types import ChunkDraft, TOCNode

logger = structlog.get_logger(__name__)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def build_chunks(
    clean_markdown: str,
    *,
    toc: list[TOCNode] | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[ChunkDraft]:
    """基于 sentence splitter 对 clean_markdown 做分块。"""

    settings = get_settings()
    size = chunk_size or settings.chunk_target_tokens * 4
    overlap = chunk_overlap or settings.chunk_overlap_tokens * 4

    if not clean_markdown.strip():
        return []

    heading_points = _build_heading_points(clean_markdown, toc or [])
    raw_chunks = _split_text(clean_markdown, chunk_size=size, overlap=overlap)
    chunks: list[ChunkDraft] = []
    for idx, (start_pos, chunk_text) in enumerate(raw_chunks):
        section_id, heading_title = _heading_for_offset(heading_points, start_pos)
        chunks.append(
            ChunkDraft(
                chunk_index=idx,
                text=chunk_text,
                token_count=max(1, len(chunk_text) // 4),
                section_id=section_id,
                heading_title=heading_title,
            )
        )
    return chunks


async def embed_chunks(chunks: list[ChunkDraft], *, user=None) -> list[ChunkDraft]:
    """调用 Embedder 生成向量，不可用时返回无向量的 chunks。"""

    if not chunks:
        return chunks

    try:
        from app.modules.settings.runtime import resolve_embedding_runtime_config
        from app.infra.ai.embedder import Embedder

        runtime_config = resolve_embedding_runtime_config(user)
        embedder = Embedder(runtime_config)
        if not embedder.is_configured:
            logger.info("index.embedder_not_configured")
            return chunks

        texts = [c.contextualized_text or c.text for c in chunks]
        settings = get_settings()
        batch_size = max(1, int(getattr(settings, "embedding_batch_size", 64)))
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset : offset + batch_size]
            batch_vecs = await embedder.embed_texts(batch)
            if not batch_vecs:
                continue
            vectors.extend(batch_vecs)

        if vectors:
            for idx, chunk in enumerate(chunks):
                if idx < len(vectors):
                    chunk.embedding = vectors[idx]
    except Exception as exc:
        logger.warning("index.embed_failed", error=str(exc))

    return chunks


def _split_text(text: str, *, chunk_size: int, overlap: int) -> list[tuple[int, str]]:
    from langchain_text_splitters import NLTKTextSplitter

    _ensure_nltk_sentence_resources()
    splitter = NLTKTextSplitter(
        separator="\n\n",
        chunk_size=max(int(chunk_size), 200),
        chunk_overlap=max(int(overlap), 0),
    )
    raw_chunks = splitter.split_text(text)
    chunks: list[tuple[int, str]] = []
    search_from = 0
    for chunk in raw_chunks:
        stripped = str(chunk or "").strip()
        if not stripped:
            continue
        start_pos = _find_chunk_offset(text, stripped, search_from=search_from)
        if start_pos < 0:
            start_pos = max(search_from, 0)
        chunks.append((start_pos, stripped))
        search_from = max(start_pos + max(len(stripped) - overlap, 1), 0)
    return chunks


def _build_heading_points(clean_markdown: str, toc: list[TOCNode]) -> list[tuple[int, str | None, str | None]]:
    if not clean_markdown:
        return []
    toc_by_slug: dict[str, TOCNode] = {}
    toc_by_title: dict[str, TOCNode] = {}
    for node in toc:
        if node.anchor:
            toc_by_slug[_slugify(node.anchor)] = node
        if node.title:
            toc_by_title[_normalize_title(node.title)] = node

    points: list[tuple[int, str | None, str | None]] = []
    offset = 0
    for line in clean_markdown.splitlines(keepends=True):
        stripped = line.strip()
        matched = _HEADING_RE.match(stripped)
        if matched:
            heading_title = matched.group(2).strip()
            slug = _slugify(heading_title)
            node = toc_by_slug.get(slug) or toc_by_title.get(_normalize_title(heading_title))
            points.append((offset, node.id if node else slug or None, heading_title or None))
        offset += len(line)
    return points


@lru_cache(maxsize=1)
def _ensure_nltk_sentence_resources() -> None:
    resources = [
        ("tokenizers/punkt", "punkt"),
        ("tokenizers/punkt_tab", "punkt_tab"),
    ]
    for path, package in resources:
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(package, quiet=True)


def _find_chunk_offset(text: str, chunk: str, *, search_from: int) -> int:
    start = text.find(chunk, max(search_from, 0))
    if start >= 0:
        return start
    compact_chunk = " ".join(chunk.split())
    if not compact_chunk:
        return -1
    search_window = text[max(search_from - 200, 0):]
    compact_window = " ".join(search_window.split())
    compact_index = compact_window.find(compact_chunk)
    if compact_index < 0:
        return -1
    needle = compact_chunk[:64]
    if not needle:
        return -1
    return text.find(needle, max(search_from - 200, 0))


def _heading_for_offset(
    heading_points: list[tuple[int, str | None, str | None]],
    offset: int,
) -> tuple[str | None, str | None]:
    if not heading_points:
        return None, None
    section_id: str | None = None
    heading_title: str | None = None
    for point_offset, point_id, point_title in heading_points:
        if point_offset > offset:
            break
        section_id = point_id
        heading_title = point_title
    return section_id, heading_title


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s-]", "", cleaned, flags=re.UNICODE).strip().lower()
    cleaned = re.sub(r"[\s_-]+", "-", cleaned)
    return cleaned
