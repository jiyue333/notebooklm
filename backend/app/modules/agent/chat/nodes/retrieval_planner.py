"""Node 2: Retrieval Planner — 根据 route 制定检索策略。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_chat_stage
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec

logger = structlog.get_logger(__name__)
_COMPLEXITY_HINTS = re.compile(
    r"(对比|比较|综述|总结|差异|trade[- ]?off|compare|contrast|analysis|synthesize|推荐|相关)",
    re.IGNORECASE,
)
_LIGHT_WEIGHT_HINTS = re.compile(
    r"(你好|hello|thanks|谢谢|简答|一句话|一句|quick|brief)",
    re.IGNORECASE,
)


async def retrieval_planner_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    scope = state.get("retrieval_scope", "none")
    article_id = state.get("article_id")
    query = str(state.get("query") or "").strip()
    notebook_article_count = max(int(state.get("notebook_article_count") or 0), 0)
    notebook_indexed_article_count = max(int(state.get("notebook_indexed_article_count") or 0), 0)
    settings = get_settings()

    def _done(plan: RetrievalPlanSpec) -> dict[str, Any]:
        observe_chat_stage(stage="retrieval_planner", route=route, status=plan.strategy, duration_ms=_ms(t0))
        return {"retrieval_plan": plan}

    if notebook_article_count > 0 and notebook_indexed_article_count <= 0:
        return _done(RetrievalPlanSpec(strategy="skip"))

    if scope == "none" and route == "general":
        return _done(RetrievalPlanSpec(strategy="skip"))

    dense_top_k, sparse_top_k, rerank_top_n = _resolve_dynamic_budget(
        query=query,
        route=route,
        notebook_article_count=notebook_article_count,
        notebook_indexed_article_count=notebook_indexed_article_count,
        base_dense=settings.chat_dense_top_k,
        base_sparse=settings.chat_sparse_top_k,
        base_rerank=settings.chat_rerank_top_n,
    )

    if route == "article_qa" and article_id:
        return _done(RetrievalPlanSpec(
            strategy="chunk_only",
            target_article_ids=[article_id],
            dense_top_k=dense_top_k,
            sparse_top_k=sparse_top_k,
            use_rerank=True,
            rerank_top_n=rerank_top_n,
        ))

    if route == "recommendation":
        # 推荐问题先做 article-level recall，再做 chunk 粗检索，预算略保守。
        return _done(RetrievalPlanSpec(
            strategy="article_then_chunk",
            dense_top_k=max(4, dense_top_k - 2),
            sparse_top_k=max(4, sparse_top_k - 2),
            use_rerank=True,
            rerank_top_n=max(3, rerank_top_n - 1),
        ))

    if route == "notebook_search" or (route == "general" and scope == "notebook"):
        factor = 1 if route == "notebook_search" else 0.55
        return _done(RetrievalPlanSpec(
            strategy="hybrid",
            dense_top_k=max(3, int(dense_top_k * factor)),
            sparse_top_k=max(3, int(sparse_top_k * factor)),
            use_rerank=True,
            rerank_top_n=max(3, int(rerank_top_n * factor)),
        ))

    return _done(RetrievalPlanSpec(strategy="skip"))


def _resolve_dynamic_budget(
    *,
    query: str,
    route: str,
    notebook_article_count: int,
    notebook_indexed_article_count: int,
    base_dense: int,
    base_sparse: int,
    base_rerank: int,
) -> tuple[int, int, int]:
    dense = max(base_dense, 2)
    sparse = max(base_sparse, 2)
    rerank = max(base_rerank, 2)

    query_terms = re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9]{2,}", query.lower())
    query_len = len(query_terms)
    complexity = 1.0
    if query_len >= 16 or _COMPLEXITY_HINTS.search(query):
        complexity += 0.25
    if query_len <= 4 or _LIGHT_WEIGHT_HINTS.search(query):
        complexity -= 0.25
    if route == "recommendation":
        complexity -= 0.1
    if route == "notebook_search":
        complexity += 0.1

    if notebook_article_count >= 80:
        complexity -= 0.15
    if notebook_article_count >= 180:
        complexity -= 0.2
    if notebook_article_count >= 320:
        complexity -= 0.2

    if notebook_article_count > 0:
        indexed_ratio = notebook_indexed_article_count / notebook_article_count
        if indexed_ratio < 0.5:
            complexity -= 0.1
        if indexed_ratio < 0.25:
            complexity -= 0.15

    complexity = max(0.45, min(complexity, 1.35))
    dense = max(3, int(round(dense * complexity)))
    sparse = max(3, int(round(sparse * complexity)))
    rerank = max(3, int(round(rerank * complexity)))

    return dense, sparse, rerank


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
