"""Phase 4 — 索引层：分块 + 向量化。"""

from __future__ import annotations

import structlog

from app.core.config import get_settings
from app.modules.ingest.types import ChunkDraft

logger = structlog.get_logger(__name__)


def build_chunks(
    clean_markdown: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[ChunkDraft]:
    """基于 clean_markdown 按字符数分块。"""

    settings = get_settings()
    size = chunk_size or settings.chunk_target_tokens * 4
    overlap = chunk_overlap or settings.chunk_overlap_tokens * 4

    if not clean_markdown.strip():
        return []

    raw_chunks = _split_text(clean_markdown, chunk_size=size, overlap=overlap)
    return [
        ChunkDraft(
            chunk_index=idx,
            text=text,
            token_count=max(1, len(text) // 4),
        )
        for idx, text in enumerate(raw_chunks)
    ]


async def embed_chunks(chunks: list[ChunkDraft]) -> list[ChunkDraft]:
    """调用 Embedder 生成向量，不可用时返回无向量的 chunks。"""

    if not chunks:
        return chunks

    try:
        from app.modules.settings.runtime import resolve_embedding_runtime_config
        from app.infra.ai.embedder import Embedder

        runtime_config = resolve_embedding_runtime_config(None)
        embedder = Embedder(runtime_config)
        if not embedder.is_configured:
            logger.info("index.embedder_not_configured")
            return chunks

        texts = [c.text for c in chunks]
        vectors = await embedder.embed_texts(texts)
        if vectors:
            for chunk, vec in zip(chunks, vectors):
                chunk.embedding = vec
    except Exception as exc:
        logger.warning("index.embed_failed", error=str(exc))

    return chunks


def _split_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
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
            chunks.append(stripped)
        start = end - overlap
        if start < 0:
            start = 0
        if end >= len(text):
            break
    return chunks
