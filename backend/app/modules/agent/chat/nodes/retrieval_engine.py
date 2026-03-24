"""Node 3: Retrieval Engine — 执行 hybrid 检索。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.telemetry.metrics import observe_chat_error, observe_chat_rerank_top_score, observe_chat_stage
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec
from app.modules.agent.retrieval.article_recall import article_recall
from app.modules.agent.retrieval.hybrid import hybrid_retrieval
from app.modules.agent.retrieval.types import HybridRetrievalRequest
from app.modules.notebooks.models import Article

logger = structlog.get_logger(__name__)


async def retrieval_engine_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    plan: RetrievalPlanSpec = state.get("retrieval_plan", RetrievalPlanSpec())
    route = state.get("route", "general")
    if plan.strategy == "skip":
        observe_chat_stage(stage="retrieval_engine", route=route, status="skip", duration_ms=_ms(t0))
        return {"local_evidence": []}

    query = state["query"]
    notebook_id = state.get("notebook_id", "")
    user = state.get("user")
    settings = get_settings()

    async for db in get_session_manager().session():
        try:
            if plan.strategy == "chunk_only":
                results = await hybrid_retrieval(db, HybridRetrievalRequest(
                    query=query,
                    scope_article_ids=plan.target_article_ids,
                    top_k=settings.chat_rerank_top_n,
                    dense_weight=settings.chat_dense_weight,
                    sparse_weight=settings.chat_sparse_weight,
                    use_rerank=plan.use_rerank,
                    rerank_top_n=plan.rerank_top_n,
                    user=user,
                ))

            elif plan.strategy == "article_then_chunk":
                articles = await article_recall(
                    db, query=query, notebook_id=notebook_id, top_k=5,
                )
                article_ids = [a.article_id for a in articles]
                if not article_ids:
                    observe_chat_stage(stage="retrieval_engine", route=route, status="empty", duration_ms=_ms(t0))
                    return {"local_evidence": []}
                results = await hybrid_retrieval(db, HybridRetrievalRequest(
                    query=query,
                    scope_article_ids=article_ids,
                    top_k=settings.chat_rerank_top_n,
                    dense_weight=settings.chat_dense_weight,
                    sparse_weight=settings.chat_sparse_weight,
                    use_rerank=plan.use_rerank,
                    rerank_top_n=plan.rerank_top_n,
                    user=user,
                ))

            elif plan.strategy == "hybrid":
                article_ids = await _get_notebook_article_ids(db, notebook_id)
                if not article_ids:
                    observe_chat_stage(stage="retrieval_engine", route=route, status="empty", duration_ms=_ms(t0))
                    return {"local_evidence": []}
                results = await hybrid_retrieval(db, HybridRetrievalRequest(
                    query=query,
                    scope_article_ids=article_ids,
                    top_k=settings.chat_rerank_top_n,
                    dense_weight=settings.chat_dense_weight,
                    sparse_weight=settings.chat_sparse_weight,
                    use_rerank=plan.use_rerank,
                    rerank_top_n=plan.rerank_top_n,
                    user=user,
                ))
            else:
                results = []

            evidence = [r.to_evidence_dict() for r in results]

            if results:
                top_score = max(r.rerank_score or r.score for r in results)
                observe_chat_rerank_top_score(score=top_score)

            observe_chat_stage(stage="retrieval_engine", route=route, status="ok", duration_ms=_ms(t0))
            logger.info("chat.retrieval_done", strategy=plan.strategy, count=len(evidence))
            return {"local_evidence": evidence}

        except Exception as exc:
            logger.exception("chat.retrieval_failed", error=str(exc)[:200])
            observe_chat_error(node="retrieval_engine")
            observe_chat_stage(stage="retrieval_engine", route=route, status="error", duration_ms=_ms(t0))
            return {"local_evidence": []}

    return {"local_evidence": []}


async def _get_notebook_article_ids(db: AsyncSession, notebook_id: str) -> list[str]:
    result = await db.execute(
        select(Article.id).where(
            Article.notebook_id == notebook_id,
            Article.index_status == "completed",
        )
    )
    return [row[0] for row in result.all()]


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
