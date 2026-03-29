"""Phase 4 — 索引层：分块 + 向量化。"""

from __future__ import annotations

import re
import unicodedata

import structlog

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
    """基于 clean_markdown 按字符数分块。"""

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
    chunks: list[tuple[int, str]] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        if end < len(text):
            last_break = chunk.rfind("\n\n")
            if last_break > chunk_size // 2:
                end = start + last_break
                chunk = text[start:end]
        stripped = chunk.strip()
        if stripped:
            chunks.append((start, stripped))
        start = end - overlap
        if start < 0:
            start = 0
        if end >= len(text):
            break
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
