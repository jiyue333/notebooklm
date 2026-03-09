from __future__ import annotations

import re
from dataclasses import dataclass

import structlog
from sqlalchemy import case, desc, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.ingest.embedder import Embedder
from app.modules.notebooks.models import Article
from app.modules.retrieval.fusion import rrf_fuse_with_details

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class RetrievedArticleMatch:
    article: Article
    score: float
    matched_by: list[str]
    snippet: str


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[\s,，。！？；:：/()（）]+", text.lower()) if len(token) >= 2]


async def retrieve_related_articles(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None = None,
    limit: int = 5,
) -> list[RetrievedArticleMatch]:
    query_text = query.strip()
    if not query_text:
        return []

    lexical_ids = await _lexical_search(
        session,
        user_id=user_id,
        query=query_text,
        exclude_article_id=exclude_article_id,
        limit=max(limit * 3, 10),
    )
    title_ids = await _title_search(
        session,
        user_id=user_id,
        query=query_text,
        exclude_article_id=exclude_article_id,
        limit=max(limit * 3, 10),
    )
    semantic_ids = await _semantic_search(
        session,
        user_id=user_id,
        query=query_text,
        exclude_article_id=exclude_article_id,
        limit=max(limit * 3, 10),
    )
    rankings = {
        name: ranking
        for name, ranking in {
            "lexical": lexical_ids,
            "title": title_ids,
            "semantic": semantic_ids,
        }.items()
        if ranking
    }
    fused_hits = rrf_fuse_with_details(rankings, limit=limit)
    if not fused_hits:
        return []

    result = await session.execute(
        select(Article)
        .options(selectinload(Article.notebook))
        .where(Article.id.in_([hit.item_id for hit in fused_hits]))
    )
    article_map = {article.id: article for article in result.scalars().all()}
    matches: list[RetrievedArticleMatch] = []
    for hit in fused_hits:
        article = article_map.get(hit.item_id)
        if article is None:
            continue
        matches.append(
            RetrievedArticleMatch(
                article=article,
                score=round(hit.score, 6),
                matched_by=hit.matched_by,
                snippet=_build_article_snippet(article, query=query_text),
            )
        )
    return matches


async def _lexical_search(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None,
    limit: int,
) -> list[str]:
    ts_query = func.websearch_to_tsquery("simple", query)
    rank_expr = func.ts_rank_cd(Article.article_tsv, ts_query)
    stmt = (
        select(Article.id)
        .where(
            Article.user_id == user_id,
            Article.parse_status != "failed",
            Article.article_tsv.op("@@")(ts_query),
        )
        .order_by(desc(rank_expr), desc(Article.updated_at))
        .limit(limit)
    )
    if exclude_article_id:
        stmt = stmt.where(Article.id != exclude_article_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _semantic_search(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None,
    limit: int,
) -> list[str]:
    embedder = Embedder()
    if not embedder.is_configured:
        return []
    try:
        embeddings = await embedder.embed_texts([query])
    except Exception as exc:
        logger.exception("retrieval.semantic_embedding_failed", error=str(exc))
        return []
    if not embeddings:
        return []
    query_vector = embeddings[0]

    distance_expr = Article.article_vector.cosine_distance(query_vector)
    stmt = (
        select(Article.id)
        .where(
            Article.user_id == user_id,
            Article.parse_status != "failed",
            Article.article_vector.is_not(None),
        )
        .order_by(distance_expr.asc(), desc(Article.updated_at))
        .limit(limit)
    )
    if exclude_article_id:
        stmt = stmt.where(Article.id != exclude_article_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _title_search(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
    exclude_article_id: str | None,
    limit: int,
) -> list[str]:
    tokens = _tokenize(query)
    if not tokens:
        return []

    score_expr = literal(0)
    filters = []
    for token in tokens:
        pattern = f"%{token}%"
        filters.append(Article.title.ilike(pattern))
        score_expr = score_expr + case((Article.title.ilike(pattern), 1), else_=0)

    stmt = (
        select(Article.id)
        .where(Article.user_id == user_id, Article.parse_status != "failed", or_(*filters))
        .order_by(desc(score_expr), desc(Article.updated_at))
        .limit(limit)
    )
    if exclude_article_id:
        stmt = stmt.where(Article.id != exclude_article_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _build_article_snippet(article: Article, *, query: str) -> str:
    text = _strip_markdown(article.clean_markdown or article.preview_markdown or article.article_retrieval_text or "")
    if not text:
        return article.title

    tokens = _tokenize(query)
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    for paragraph in paragraphs:
        lowered = paragraph.lower()
        if any(token in lowered for token in tokens):
            return _truncate(paragraph)
    return _truncate(paragraphs[0] if paragraphs else text)


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```.*?```", " ", text, flags=re.S)
    cleaned = re.sub(r"`([^`]*)`", r"\1", cleaned)
    cleaned = re.sub(r"!\[.*?\]\(.*?\)", " ", cleaned)
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    cleaned = re.sub(r"^[#>\-\*\+\d\.\s]+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _truncate(text: str, *, limit: int = 220) -> str:
    value = " ".join(text.split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3].rstrip()}..."
