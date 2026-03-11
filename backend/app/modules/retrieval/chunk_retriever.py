from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.embedder import Embedder
from app.modules.auth.repo import get_user_by_id
from app.modules.notebooks.models import Article, ArticleChunk
from app.modules.retrieval.fusion import rrf_fuse_with_details

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class RetrievedChunkMatch:
    article: Article
    chunk: ArticleChunk
    score: float
    matched_by: list[str]
    snippet: str


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[\s,，。！？；:：/()（）]+", text.lower()) if len(token) >= 2]


async def retrieve_notebook_evidence_chunks(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    limit: int = 5,
) -> list[RetrievedChunkMatch]:
    query_text = query.strip()
    if not query_text:
        return []

    lexical_ids = await _lexical_search(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        query=query_text,
        limit=max(limit * 3, 12),
    )
    semantic_ids = await _semantic_search(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        query=query_text,
        limit=max(limit * 3, 12),
    )
    rankings = {
        name: ranking
        for name, ranking in {
            "lexical": lexical_ids,
            "semantic": semantic_ids,
        }.items()
        if ranking
    }
    fused_hits = rrf_fuse_with_details(rankings, limit=limit)
    if not fused_hits:
        return []

    result = await session.execute(
        select(ArticleChunk, Article)
        .join(Article, Article.id == ArticleChunk.article_id)
        .where(ArticleChunk.id.in_([hit.item_id for hit in fused_hits]))
    )
    chunk_rows = {
        chunk.id: (chunk, article)
        for chunk, article in result.all()
    }
    matches: list[RetrievedChunkMatch] = []
    for hit in fused_hits:
        row = chunk_rows.get(hit.item_id)
        if row is None:
            continue
        chunk, article = row
        matches.append(
            RetrievedChunkMatch(
                article=article,
                chunk=chunk,
                score=round(hit.score, 6),
                matched_by=hit.matched_by,
                snippet=_build_chunk_snippet(chunk.chunk_text, query=query_text),
            )
        )
    return matches


async def _lexical_search(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    limit: int,
) -> list[str]:
    ts_query = func.websearch_to_tsquery("simple", query)
    chunk_tsv = func.to_tsvector("simple", ArticleChunk.chunk_text)
    rank_expr = func.ts_rank_cd(chunk_tsv, ts_query)
    result = await session.execute(
        select(ArticleChunk.id)
        .join(Article, Article.id == ArticleChunk.article_id)
        .where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
            Article.parse_status == "ready",
            chunk_tsv.op("@@")(ts_query),
        )
        .order_by(desc(rank_expr), desc(Article.updated_at), ArticleChunk.chunk_index.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def _semantic_search(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    limit: int,
) -> list[str]:
    user = await get_user_by_id(session, user_id)
    if user is None:
        return []
    embedder = Embedder.from_user(user)
    if not embedder.is_configured:
        return []
    try:
        embeddings = await embedder.embed_texts([query])
    except Exception as exc:
        logger.exception("retrieval.chunk_semantic_embedding_failed", error=str(exc))
        return []
    if not embeddings:
        return []

    query_vector = embeddings[0]
    vector_dim = len(query_vector)
    distance_expr = ArticleChunk.chunk_vector.cosine_distance(query_vector)
    result = await session.execute(
        select(ArticleChunk.id)
        .join(Article, Article.id == ArticleChunk.article_id)
        .where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
            Article.parse_status == "ready",
            Article.embedding_profile_key == embedder.profile_key,
            Article.embedding_dimension == vector_dim,
            ArticleChunk.chunk_vector.is_not(None),
        )
        .order_by(distance_expr.asc(), desc(Article.updated_at), ArticleChunk.chunk_index.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _build_chunk_snippet(text: str, *, query: str, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if not normalized:
        return ""

    tokens = _tokenize(query)
    lowered = normalized.lower()
    for token in tokens:
        index = lowered.find(token)
        if index >= 0:
            start = max(0, index - 80)
            end = min(len(normalized), index + max(limit, len(token) + 80))
            snippet = normalized[start:end].strip()
            if start > 0:
                snippet = f"...{snippet}"
            if end < len(normalized):
                snippet = f"{snippet}..."
            return snippet
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3].rstrip()}..."
