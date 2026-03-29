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
    dense_top_k = max(plan.dense_top_k or settings.chat_dense_top_k, 1)
    sparse_top_k = max(plan.sparse_top_k or settings.chat_sparse_top_k, 1)
    rerank_top_n = max(plan.rerank_top_n or settings.chat_rerank_top_n, 1)

    session = state.get("db")
    if isinstance(session, AsyncSession):
        return await _run_retrieval_with_session(
            session,
            state=state,
            plan=plan,
            route=route,
            query=query,
            notebook_id=notebook_id,
            user=user,
            settings=settings,
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            rerank_top_n=rerank_top_n,
            started=t0,
        )

    async for db in get_session_manager().session():
        return await _run_retrieval_with_session(
            db,
            state=state,
            plan=plan,
            route=route,
            query=query,
            notebook_id=notebook_id,
            user=user,
            settings=settings,
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            rerank_top_n=rerank_top_n,
            started=t0,
        )
    return {"local_evidence": []}


async def _run_retrieval_with_session(
    db: AsyncSession,
    *,
    state: ChatGraphState,
    plan: RetrievalPlanSpec,
    route: str,
    query: str,
    notebook_id: str,
    user,
    settings,
    dense_top_k: int,
    sparse_top_k: int,
    rerank_top_n: int,
    started: float,
) -> dict[str, Any]:
    try:
        if plan.strategy == "chunk_only":
            target_article_ids = plan.target_article_ids
            results = await hybrid_retrieval(db, HybridRetrievalRequest(
                query=query,
                scope_article_ids=target_article_ids,
                top_k=rerank_top_n,
                dense_top_k=dense_top_k,
                sparse_top_k=sparse_top_k,
                dense_weight=settings.chat_dense_weight,
                sparse_weight=settings.chat_sparse_weight,
                use_rerank=plan.use_rerank,
                rerank_top_n=rerank_top_n,
                user=user,
            ))
        elif plan.strategy == "article_then_chunk":
            articles = await article_recall(
                db,
                query=query,
                notebook_id=notebook_id,
                top_k=min(max(rerank_top_n, 5), 8),
            )
            target_article_ids = [a.article_id for a in articles]
            if not target_article_ids:
                fallback = await _build_fallback_evidence(db, plan.target_article_ids, notebook_id)
                observe_chat_stage(stage="retrieval_engine", route=route, status="fallback", duration_ms=_ms(started))
                return {"local_evidence": fallback}
            results = await hybrid_retrieval(db, HybridRetrievalRequest(
                query=query,
                scope_article_ids=target_article_ids,
                top_k=rerank_top_n,
                dense_top_k=dense_top_k,
                sparse_top_k=sparse_top_k,
                dense_weight=settings.chat_dense_weight,
                sparse_weight=settings.chat_sparse_weight,
                use_rerank=plan.use_rerank,
                rerank_top_n=rerank_top_n,
                user=user,
            ))
        elif plan.strategy == "hybrid":
            target_article_ids = await _get_notebook_article_ids(
                db,
                notebook_id,
                query=query,
                cap=max(int(settings.chat_notebook_scope_article_cap), 12),
            )
            if not target_article_ids:
                fallback = await _build_fallback_evidence(db, [], notebook_id)
                observe_chat_stage(stage="retrieval_engine", route=route, status="fallback", duration_ms=_ms(started))
                return {"local_evidence": fallback}
            results = await hybrid_retrieval(db, HybridRetrievalRequest(
                query=query,
                scope_article_ids=target_article_ids,
                top_k=rerank_top_n,
                dense_top_k=dense_top_k,
                sparse_top_k=sparse_top_k,
                dense_weight=settings.chat_dense_weight,
                sparse_weight=settings.chat_sparse_weight,
                use_rerank=plan.use_rerank,
                rerank_top_n=rerank_top_n,
                user=user,
            ))
        else:
            target_article_ids = []
            results = []

        evidence = [r.to_evidence_dict() for r in results]
        if not evidence:
            fallback = await _build_fallback_evidence(db, target_article_ids, notebook_id)
            if fallback:
                observe_chat_stage(stage="retrieval_engine", route=route, status="fallback", duration_ms=_ms(started))
                return {"local_evidence": fallback}

        if results:
            top_score = max(r.rerank_score or r.score for r in results)
            observe_chat_rerank_top_score(score=top_score)

        observe_chat_stage(stage="retrieval_engine", route=route, status="ok", duration_ms=_ms(started))
        logger.info("chat.retrieval_done", strategy=plan.strategy, count=len(evidence))
        return {"local_evidence": evidence}
    except Exception as exc:
        logger.exception("chat.retrieval_failed", error=str(exc)[:200])
        fallback = await _build_fallback_evidence(db, plan.target_article_ids, notebook_id)
        observe_chat_error(node="retrieval_engine")
        observe_chat_stage(stage="retrieval_engine", route=route, status="error", duration_ms=_ms(started))
        return {"local_evidence": fallback}


async def _get_notebook_article_ids(
    db: AsyncSession,
    notebook_id: str,
    *,
    query: str,
    cap: int,
) -> list[str]:
    result = await db.execute(
        select(Article.id).where(
            Article.notebook_id == notebook_id,
            Article.index_status == "completed",
        )
    )
    all_ids = [row[0] for row in result.all()]
    if len(all_ids) <= cap:
        return all_ids
    recalled = await article_recall(
        db,
        query=query,
        notebook_id=notebook_id,
        top_k=min(cap, 24),
    )
    recalled_ids = [item.article_id for item in recalled]
    if recalled_ids:
        return recalled_ids
    return all_ids[:cap]


async def _build_fallback_evidence(
    db: AsyncSession,
    article_ids: list[str],
    notebook_id: str,
) -> list[dict]:
    candidates = list(dict.fromkeys([aid for aid in article_ids if aid]))
    if not candidates:
        result = await db.execute(
            select(Article.id).where(
                Article.notebook_id == notebook_id,
            ).order_by(Article.updated_at.desc()).limit(3)
        )
        candidates = [row[0] for row in result.all()]
    if not candidates:
        return []

    result = await db.execute(
        select(
            Article.id,
            Article.title,
            Article.article_retrieval_text,
            Article.preview_markdown,
            Article.clean_markdown,
        ).where(Article.id.in_(candidates)).limit(3)
    )
    evidence: list[dict] = []
    for row in result.all():
        text = (
            (row.article_retrieval_text or "").strip()
            or (row.preview_markdown or "").strip()
            or (row.clean_markdown or "").strip()
        )
        if not text:
            continue
        evidence.append({
            "chunk_id": f"article_fallback:{row.id}",
            "article_id": row.id,
            "article_title": row.title or "",
            "raw_text": text[:420],
            "score": 0.22,
            "section_path": "article_summary",
            "heading_title": "摘要降级证据",
        })
    return evidence


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
