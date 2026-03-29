"""Hybrid retrieval — dense + sparse + RRF + rerank。"""

from __future__ import annotations

from collections import defaultdict
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.reranker import build_reranker
from app.infra.telemetry.metrics import observe_retrieval_stage
from app.modules.agent.retrieval.dense import dense_retrieval, embed_query
from app.modules.agent.retrieval.sparse import sparse_retrieval
from app.modules.agent.retrieval.types import HybridRetrievalRequest, RetrievalResult

logger = structlog.get_logger(__name__)

_RRF_K = 60


def _rrf_fuse(
    dense_results: list[RetrievalResult],
    sparse_results: list[RetrievalResult],
    *,
    dense_weight: float = 0.7,
    sparse_weight: float = 0.3,
) -> list[RetrievalResult]:
    """Reciprocal Rank Fusion。"""

    scores: dict[str, float] = defaultdict(float)
    result_map: dict[str, RetrievalResult] = {}

    for rank, r in enumerate(dense_results):
        scores[r.chunk_id] += dense_weight / (rank + _RRF_K)
        result_map[r.chunk_id] = r

    for rank, r in enumerate(sparse_results):
        scores[r.chunk_id] += sparse_weight / (rank + _RRF_K)
        if r.chunk_id not in result_map:
            result_map[r.chunk_id] = r
        else:
            result_map[r.chunk_id].sparse_score = r.sparse_score

    for chunk_id, fused_score in scores.items():
        result_map[chunk_id].score = fused_score

    ranked = sorted(result_map.values(), key=lambda x: x.score, reverse=True)
    return ranked


async def hybrid_retrieval(
    db: AsyncSession,
    request: HybridRetrievalRequest,
) -> list[RetrievalResult]:
    """执行 hybrid 检索：dense ∥ sparse → RRF → 可选 rerank。"""

    if not request.scope_article_ids:
        return []

    # ========== phase 1 检索 ==========
    t_embed = perf_counter()
    query_vec = await embed_query(request.query, user=request.user)
    observe_retrieval_stage(stage="embed_query", duration_ms=_ms(t_embed))

    dense_results: list[RetrievalResult] = []
    dense_top_k = max(request.dense_top_k or request.top_k, 1)
    sparse_top_k = max(request.sparse_top_k or request.top_k, 1)
    if query_vec:
        t_dense = perf_counter()
        try:
            dense_results = await dense_retrieval(
                db,
                query_embedding=query_vec,
                scope_article_ids=request.scope_article_ids,
                top_k=dense_top_k * 2,
            )
        except Exception as exc:
            logger.warning("hybrid.dense_failed", error=str(exc)[:200])
        observe_retrieval_stage(stage="dense", duration_ms=_ms(t_dense), count=len(dense_results))

    t_sparse = perf_counter()
    sparse_results: list[RetrievalResult] = []
    try:
        sparse_results = await sparse_retrieval(
            db,
            query=request.query,
            scope_article_ids=request.scope_article_ids,
            top_k=sparse_top_k * 2,
        )
    except Exception as exc:
        logger.warning("hybrid.sparse_failed", error=str(exc)[:200])
    observe_retrieval_stage(stage="sparse", duration_ms=_ms(t_sparse), count=len(sparse_results))

    # ========== phase 2 RRF 融合 ==========
    t_fuse = perf_counter()
    fused = _rrf_fuse(
        dense_results,
        sparse_results,
        dense_weight=request.dense_weight,
        sparse_weight=request.sparse_weight,
    )
    observe_retrieval_stage(stage="rrf_fuse", duration_ms=_ms(t_fuse), count=len(fused))

    if not fused:
        return []

    # ========== phase 3 可选 rerank ==========
    if request.use_rerank:
        reranker = build_reranker()
        if reranker is not None:
            rerank_top = request.rerank_top_n or request.top_k
            candidates = fused[: rerank_top * 2]
            t_rerank = perf_counter()
            try:
                rr = await reranker.rerank(
                    request.query,
                    [c.contextualized_text for c in candidates],
                    top_n=rerank_top,
                )
                reranked: list[RetrievalResult] = []
                for item in rr:
                    if item.index < len(candidates):
                        r = candidates[item.index]
                        r.rerank_score = item.relevance_score
                        r.score = item.relevance_score
                        reranked.append(r)
                observe_retrieval_stage(stage="rerank", duration_ms=_ms(t_rerank), count=len(reranked))
                return reranked[: request.top_k]
            except Exception as exc:
                logger.warning("hybrid.rerank_failed", error=str(exc)[:200])
                observe_retrieval_stage(stage="rerank", duration_ms=_ms(t_rerank))

    return fused[: request.top_k]


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
