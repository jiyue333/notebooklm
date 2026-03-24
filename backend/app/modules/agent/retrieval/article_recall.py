"""Article-level recall — dense + sparse 融合召回文章。"""

from __future__ import annotations

import asyncio
from collections import defaultdict

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.retrieval.dense import embed_query
from app.modules.agent.retrieval.types import ArticleRecallResult
from app.modules.notebooks.models import Article

logger = structlog.get_logger(__name__)

_RRF_K = 60


async def article_recall(
    db: AsyncSession,
    *,
    query: str,
    notebook_id: str,
    top_k: int = 5,
) -> list[ArticleRecallResult]:
    """在 notebook 内按 article 粒度召回。"""

    dense_task = _article_dense(db, query=query, notebook_id=notebook_id, top_k=top_k * 2)
    sparse_task = _article_sparse(db, query=query, notebook_id=notebook_id, top_k=top_k * 2)

    dense_results, sparse_results = await asyncio.gather(
        dense_task, sparse_task, return_exceptions=True,
    )
    if isinstance(dense_results, BaseException):
        logger.warning("article_recall.dense_failed", error=str(dense_results)[:200])
        dense_results = []
    if isinstance(sparse_results, BaseException):
        logger.warning("article_recall.sparse_failed", error=str(sparse_results)[:200])
        sparse_results = []

    scores: dict[str, float] = defaultdict(float)
    result_map: dict[str, ArticleRecallResult] = {}

    for rank, r in enumerate(dense_results):
        scores[r.article_id] += 0.7 / (rank + _RRF_K)
        result_map[r.article_id] = r

    for rank, r in enumerate(sparse_results):
        scores[r.article_id] += 0.3 / (rank + _RRF_K)
        if r.article_id not in result_map:
            result_map[r.article_id] = r

    for aid, s in scores.items():
        result_map[aid].score = s

    ranked = sorted(result_map.values(), key=lambda x: x.score, reverse=True)
    return ranked[:top_k]


async def _article_dense(
    db: AsyncSession,
    *,
    query: str,
    notebook_id: str,
    top_k: int,
) -> list[ArticleRecallResult]:
    query_vec = await embed_query(query)
    if not query_vec:
        return []

    stmt = (
        select(
            Article.id,
            Article.title,
            Article.article_vector.cosine_distance(query_vec).label("distance"),
        )
        .where(
            Article.notebook_id == notebook_id,
            Article.article_vector.isnot(None),
        )
        .order_by("distance")
        .limit(top_k)
    )
    result = await db.execute(stmt)
    return [
        ArticleRecallResult(
            article_id=row.id,
            title=row.title,
            score=1.0 - row.distance,
        )
        for row in result.all()
    ]


async def _article_sparse(
    db: AsyncSession,
    *,
    query: str,
    notebook_id: str,
    top_k: int,
) -> list[ArticleRecallResult]:
    if not query.strip():
        return []

    tsquery = func.plainto_tsquery("simple", query)

    stmt = (
        select(
            Article.id,
            Article.title,
            func.ts_rank_cd(Article.article_tsv, tsquery).label("rank"),
        )
        .where(
            Article.notebook_id == notebook_id,
            Article.article_tsv.op("@@")(tsquery),
        )
        .order_by(func.ts_rank_cd(Article.article_tsv, tsquery).desc())
        .limit(top_k)
    )
    result = await db.execute(stmt)
    return [
        ArticleRecallResult(
            article_id=row.id,
            title=row.title,
            score=float(row.rank),
        )
        for row in result.all()
    ]
