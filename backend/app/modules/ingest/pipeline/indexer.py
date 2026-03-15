"""Stage I – Chunk, Embed & Index.

Splits the block graph into retrieval-friendly chunks, generates
embeddings, and produces ``ChunkDraft`` objects ready for persistence.
"""

from __future__ import annotations

import structlog

from app.infra.ai.embedder import Embedder
from app.modules.ingest.pipeline.types import BlockGraph, BlockType, ChunkDraft

logger = structlog.get_logger(__name__)

_DEFAULT_CHUNK_SIZE = 800
_DEFAULT_CHUNK_OVERLAP = 100


def build_chunks(
    graph: BlockGraph,
    *,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = _DEFAULT_CHUNK_OVERLAP,
) -> list[ChunkDraft]:
    """Split block graph text into overlapping chunks."""

    full_text = _linearize(graph)
    if not full_text.strip():
        return []

    raw_chunks = _split_text(full_text, chunk_size=chunk_size, overlap=chunk_overlap)

    drafts: list[ChunkDraft] = []
    for idx, text in enumerate(raw_chunks):
        section_id = _infer_section(text, graph)
        drafts.append(ChunkDraft(
            chunk_index=idx,
            text=text,
            token_count=_approx_tokens(text),
            section_id=section_id,
        ))

    return drafts


async def embed_chunks(
    chunks: list[ChunkDraft],
) -> list[ChunkDraft]:
    """Generate embedding vectors for each chunk.

    Uses the project's ``Embedder`` infrastructure.  If the embedder
    is unavailable, chunks are returned without vectors.
    """

    if not chunks:
        return chunks

    try:
        from app.modules.settings.runtime import resolve_embedding_runtime_config

        runtime_config = resolve_embedding_runtime_config(None)
        embedder = Embedder(runtime_config)
        if not embedder.is_configured:
            logger.info("ingest.indexer.embedder_not_configured")
            return chunks

        texts = [c.text for c in chunks]
        vectors = await embedder.embed_texts(texts)
        if vectors:
            for chunk, vec in zip(chunks, vectors):
                chunk.embedding = vec
    except Exception as exc:
        logger.warning("ingest.indexer.embed_failed", error=str(exc))

    return chunks


# ── helpers ────────────────────────────────────────────────────────────────

def _linearize(graph: BlockGraph) -> str:
    """Concatenate block texts in order, with double-newline separators."""
    parts: list[str] = []
    for b in graph.blocks:
        if b.block_type == BlockType.HEADING:
            parts.append(b.text)
        else:
            parts.append(b.text)
    return "\n\n".join(parts)


def _split_text(
    text: str,
    *,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """Simple character-based splitter with overlap."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        # try to break at a paragraph boundary
        if end < len(text):
            last_break = chunk.rfind("\n\n")
            if last_break > chunk_size // 2:
                end = start + last_break
                chunk = text[start:end]
        chunks.append(chunk.strip())
        start = end - overlap
        if start < 0:
            start = 0
        if end >= len(text):
            break
    return [c for c in chunks if c]


def _infer_section(chunk_text: str, graph: BlockGraph) -> str | None:
    """Best-effort section assignment for a chunk."""
    for b in graph.blocks:
        if b.block_type == BlockType.HEADING and b.text in chunk_text:
            return b.section_id
    return None


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)
