"""Node 2: Retrieval Planner — 根据 route 制定检索策略。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_chat_stage
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec

logger = structlog.get_logger(__name__)


async def retrieval_planner_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    scope = state.get("retrieval_scope", "none")
    article_id = state.get("article_id")
    settings = get_settings()

    def _done(plan: RetrievalPlanSpec) -> dict[str, Any]:
        observe_chat_stage(stage="retrieval_planner", route=route, status=plan.strategy, duration_ms=_ms(t0))
        return {"retrieval_plan": plan}

    if scope == "none" and route == "general":
        return _done(RetrievalPlanSpec(strategy="skip"))

    if route == "article_qa" and article_id:
        return _done(RetrievalPlanSpec(
            strategy="chunk_only",
            target_article_ids=[article_id],
            dense_top_k=settings.chat_dense_top_k,
            sparse_top_k=settings.chat_sparse_top_k,
            use_rerank=True,
            rerank_top_n=settings.chat_rerank_top_n,
        ))

    if route == "recommendation":
        return _done(RetrievalPlanSpec(
            strategy="article_then_chunk",
            dense_top_k=settings.chat_dense_top_k,
            sparse_top_k=settings.chat_sparse_top_k,
            use_rerank=True,
            rerank_top_n=settings.chat_rerank_top_n,
        ))

    if route == "notebook_search" or (route == "general" and scope == "notebook"):
        factor = 1 if route == "notebook_search" else 0.5
        return _done(RetrievalPlanSpec(
            strategy="hybrid",
            dense_top_k=int(settings.chat_dense_top_k * factor),
            sparse_top_k=int(settings.chat_sparse_top_k * factor),
            use_rerank=True,
            rerank_top_n=int(settings.chat_rerank_top_n * factor) or 4,
        ))

    return _done(RetrievalPlanSpec(strategy="skip"))


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
