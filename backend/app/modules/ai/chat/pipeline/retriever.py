"""Stage B – Route-Specific Retrieval.

Each lane has its own retrieval strategy:
  - article_grounded:  block/section semantic + lexical within one article
  - general:           no retrieval
  - recommendation:    article-level synopsis retrieval across notebooks
  - notebook_research: two-stage (article shortlist → section evidence)

First version uses simple text-matching heuristics.  A future version
plugs in the Embedder + pgvector for real semantic search.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.chat.pipeline.types import (
    ChatInput,
    ChatRoute,
    EvidenceChunk,
    EvidenceCluster,
    RecommendedArticle,
    RetrievalResult,
    RouteDecision,
)
from app.modules.notebooks.models import Article, ArticleChunk

logger = structlog.get_logger(__name__)


async def retrieve(
    db: AsyncSession,
    chat_input: ChatInput,
    decision: RouteDecision,
) -> RetrievalResult:
    """Dispatch to the correct retrieval lane."""

    route = decision.route

    if route == ChatRoute.ARTICLE_GROUNDED:
        return await _retrieve_article_grounded(db, chat_input)
    if route == ChatRoute.RECOMMENDATION:
        return await _retrieve_recommendations(db, chat_input)
    if route == ChatRoute.NOTEBOOK_RESEARCH:
        return await _retrieve_notebook_research(db, chat_input)

    # GENERAL / AMBIGUOUS – no retrieval
    return RetrievalResult(route=route)


# ── article_grounded ───────────────────────────────────────────────────────

async def _retrieve_article_grounded(
    db: AsyncSession,
    inp: ChatInput,
) -> RetrievalResult:
    if not inp.article_id:
        return RetrievalResult(route=ChatRoute.ARTICLE_GROUNDED)

    result = await db.execute(
        select(ArticleChunk)
        .where(ArticleChunk.article_id == inp.article_id)
        .order_by(ArticleChunk.chunk_index.asc())
        .limit(40)
    )
    chunks = list(result.scalars().all())

    query_tokens = _tokenize(inp.question)
    highlight_tokens = _tokenize(" ".join(inp.recent_highlights))
    cursor_section = inp.reading_cursor.section_id if inp.reading_cursor else None
    scored: list[tuple[ArticleChunk, float, float]] = []  # (chunk, total_score, query_overlap)
    for chunk in chunks:
        overlap = len(query_tokens & _tokenize(chunk.chunk_text or ""))
        query_score = overlap / max(len(query_tokens), 1)
        score = query_score
        if highlight_tokens:
            score += 0.15 * (len(highlight_tokens & _tokenize(chunk.chunk_text or "")) / max(len(highlight_tokens), 1))
        if cursor_section and getattr(chunk, "section_path", None) == cursor_section:
            score += 0.25
        scored.append((chunk, score, query_score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:5]

    # Require at least some query overlap – don't return cursor-only chunks for unrelated queries
    evidence = [
        EvidenceChunk(
            article_id=inp.article_id,
            chunk_id=c.id,
            section_id=getattr(c, "section_path", None),
            text=(c.chunk_text or "")[:300],
            score=round(s, 4),
            matched_by="lexical",
        )
        for c, s, qs in top if s > 0 and qs > 0
    ]

    return RetrievalResult(route=ChatRoute.ARTICLE_GROUNDED, evidence_chunks=evidence)


# ── recommendation ─────────────────────────────────────────────────────────

async def _retrieve_recommendations(
    db: AsyncSession,
    inp: ChatInput,
) -> RetrievalResult:
    current_article = None
    if inp.article_id:
        current_article = await db.get(Article, inp.article_id)

    result = await db.execute(
        select(Article)
        .where(
            Article.user_id == inp.user_id,
            Article.id != inp.article_id,
        )
        .limit(30)
    )
    articles = list(result.scalars().all())

    query_tokens = _tokenize(inp.question)
    current_article_tokens = _tokenize(_article_memory_text(current_article)) if current_article else set()
    scored: list[tuple[Article, float]] = []
    for art in articles:
        memory_text = _article_memory_text(art)
        memory_tokens = _tokenize(memory_text)
        topic_overlap = len(query_tokens & memory_tokens) / max(len(query_tokens), 1)
        memory_overlap = len(current_article_tokens & memory_tokens) / max(len(current_article_tokens), 1) if current_article_tokens else 0.0
        title_overlap = len(_tokenize(art.title or "") & current_article_tokens) / max(len(current_article_tokens), 1) if current_article_tokens else 0.0
        score = 0.5 * topic_overlap + 0.35 * memory_overlap + 0.15 * title_overlap
        scored.append((art, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:5]

    recommendations = [
        RecommendedArticle(
            article_id=a.id,
            title=a.title or "",
            notebook_id=a.notebook_id,
            score=round(s, 4),
            why_similar=_describe_similarity(inp.question, current_article, a),
            snippet=_article_memory_text(a)[:200],
        )
        for a, s in top if s > 0
    ]

    return RetrievalResult(route=ChatRoute.RECOMMENDATION, recommended_articles=recommendations)


# ── notebook_research ──────────────────────────────────────────────────────

async def _retrieve_notebook_research(
    db: AsyncSession,
    inp: ChatInput,
) -> RetrievalResult:
    # Phase 1: article shortlist
    result = await db.execute(
        select(Article)
        .where(
            Article.user_id == inp.user_id,
            Article.notebook_id == inp.notebook_id,
        )
        .limit(20)
    )
    articles = list(result.scalars().all())
    query_tokens = _tokenize(f"{inp.question} {' '.join(inp.recent_highlights)}")

    art_scored: list[tuple[Article, float]] = []
    for art in articles:
        article_tokens = _tokenize(_article_memory_text(art))
        score = len(query_tokens & article_tokens) / max(len(query_tokens), 1)
        art_scored.append((art, score))
    art_scored.sort(key=lambda x: x[1], reverse=True)
    shortlist = [a for a, s in art_scored[:8]]

    # Phase 2: section evidence from shortlisted articles
    evidence: list[EvidenceChunk] = []
    for art in shortlist[:5]:
        chunk_result = await db.execute(
            select(ArticleChunk)
            .where(ArticleChunk.article_id == art.id)
            .order_by(ArticleChunk.chunk_index.asc())
            .limit(10)
        )
        for chunk in chunk_result.scalars().all():
            overlap = len(query_tokens & _tokenize(chunk.chunk_text or ""))
            if overlap > 0:
                evidence.append(EvidenceChunk(
                    article_id=art.id,
                    chunk_id=chunk.id,
                    section_id=getattr(chunk, "section_path", None),
                    text=(chunk.chunk_text or "")[:300],
                    score=round(overlap / max(len(query_tokens), 1), 4),
                    matched_by="lexical",
                ))

    evidence.sort(key=lambda e: e.score, reverse=True)
    evidence = evidence[:10]

    clusters = _cluster_evidence(evidence, shortlist)

    return RetrievalResult(
        route=ChatRoute.NOTEBOOK_RESEARCH,
        evidence_chunks=evidence,
        evidence_clusters=clusters,
        article_shortlist_ids=[a.id for a in shortlist],
    )


def _cluster_evidence(
    evidence: list[EvidenceChunk],
    articles: list[Article],
) -> list[EvidenceCluster]:
    """Group evidence by article as a simple first-pass clustering."""
    art_map: dict[str, list[EvidenceChunk]] = {}
    for e in evidence:
        art_map.setdefault(e.article_id, []).append(e)

    title_map = {a.id: a.title or "未命名" for a in articles}
    return [
        EvidenceCluster(
            label=title_map.get(aid, aid),
            chunks=chunks,
            article_ids=[aid],
        )
        for aid, chunks in art_map.items()
    ]


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"\w{3,}", text.lower()))


def _article_memory_text(article: Article | None) -> str:
    if article is None:
        return ""
    return " ".join(filter(None, [
        article.title or "",
        article.article_retrieval_text or "",
        article.preview_markdown or "",
    ]))


def _describe_similarity(
    question: str,
    current_article: Article | None,
    candidate: Article,
) -> str:
    candidate_text = _article_memory_text(candidate)
    current_text = _article_memory_text(current_article)
    question_overlap = len(_tokenize(question) & _tokenize(candidate_text))
    current_overlap = len(_tokenize(current_text) & _tokenize(candidate_text)) if current_text else 0

    if current_overlap >= 6:
        return "文章摘要与当前文章相似"
    if question_overlap >= 4:
        return "主题相关"
    return "笔记本内相关"
