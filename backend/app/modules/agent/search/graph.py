"""搜索编排：意图识别、召回、打分、组卡。"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib.parse import urlparse

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.infra.telemetry.metrics import (
    observe_search_dedup,
    observe_search_e2e,
    observe_search_empty_slate,
    observe_search_slate_card_count,
    observe_search_stage,
)
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search.models import (
    CoverageFacet,
    IntentAnalysis,
    RawSearchItem,
    ScoredItem,
    ScoringOutput,
    SearchCardOut,
)
from app.modules.agent.search.prompts import (
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_TEMPLATE,
    SCORER_SYSTEM_PROMPT,
    SCORER_USER_TEMPLATE,
)
from app.modules.agent.tools.exa_search import exa_search
from app.modules.agent.tools.web_search import ddg_news, ddg_search

logger = structlog.get_logger(__name__)


async def run_search_agent(
    chat_model,
    lite_model,
    *,
    query: str,
    exa_api_key: str,
    exa_mode: str = "auto",
    notebook_title: str = "",
    existing_article_titles: list[str] | None = None,
    existing_article_urls: list[str] | None = None,
    max_results: int = 15,
) -> dict[str, Any]:
    """执行完整搜索编排。"""
    from time import perf_counter

    existing_titles = existing_article_titles or []
    existing_urls = set(existing_article_urls or [])
    pipeline_start = perf_counter()

    # ========== phase 1 意图识别 ==========
    # ====== step 1 生成结构化意图 ======
    t0 = perf_counter()
    with start_span("search.intent", attributes={"search.mode": exa_mode}):
        intent = await _phase_intent(
            lite_model,
            query=query,
            notebook_title=notebook_title,
            existing_titles=existing_titles,
        )
    observe_search_stage(
        stage="intent", mode=exa_mode, status="success",
        duration_ms=_elapsed_ms(t0),
    )
    logger.info(
        "search_agent.intent_done",
        intent=intent.intent.value,
        domain=intent.domain,
        query_count=len(intent.reformulated_queries),
        duration_ms=_elapsed_ms(t0),
    )

    # ========== phase 2 并行召回 ==========
    # ====== step 1 并发执行搜索工具 ======
    t0 = perf_counter()
    with start_span("search.recall", attributes={"search.mode": exa_mode}):
        raw_items = await _phase_recall(
            intent=intent,
            query=query,
            exa_api_key=exa_api_key,
            exa_mode=exa_mode,
            max_results=max_results,
        )
    observe_search_stage(
        stage="recall", mode=exa_mode, status="success",
        duration_ms=_elapsed_ms(t0),
    )
    logger.info("search_agent.recall_done", raw_count=len(raw_items), duration_ms=_elapsed_ms(t0))

    if not raw_items:
        observe_search_empty_slate(mode=exa_mode, reason="no_recall_results")
        observe_search_e2e(mode=exa_mode, duration_ms=_elapsed_ms(pipeline_start))
        return {
            "cards": [],
            "intent": intent.model_dump(),
            "raw_count": 0,
            "scored_count": 0,
            "card_count": 0,
        }

    # ========== phase 3 URL 去重 ==========
    # ====== step 1 归一化并去重 ======
    t0 = perf_counter()
    deduped = _deduplicate(raw_items)
    removed = len(raw_items) - len(deduped)
    if removed > 0:
        observe_search_dedup(mode=exa_mode, dedup_type="url", count=removed)
    observe_search_stage(
        stage="dedup", mode=exa_mode, status="success",
        duration_ms=_elapsed_ms(t0),
    )
    logger.info("search_agent.dedup_done", before=len(raw_items), after=len(deduped))

    # ========== phase 4 打分排序 ==========
    # ====== step 1 结构化打分 ======
    t0 = perf_counter()
    with start_span("search.score", attributes={"search.mode": exa_mode}):
        scored = await _phase_score(
            lite_model or chat_model,
            candidates=deduped,
            intent=intent,
            query=query,
            notebook_title=notebook_title,
            existing_titles=existing_titles,
        )
    observe_search_stage(
        stage="score", mode=exa_mode, status="success",
        duration_ms=_elapsed_ms(t0),
    )
    logger.info("search_agent.score_done", scored_count=len(scored), duration_ms=_elapsed_ms(t0))

    # ========== phase 5 组装结果卡片 ==========
    # ====== step 1 转换前端卡片 ======
    cards = _build_cards(scored, existing_urls=existing_urls, max_results=max_results)
    observe_search_slate_card_count(mode=exa_mode, count=len(cards))
    if not cards:
        observe_search_empty_slate(mode=exa_mode, reason="slate_empty_after_build")
    observe_search_e2e(mode=exa_mode, duration_ms=_elapsed_ms(pipeline_start))
    logger.info(
        "search_agent.cards_built",
        card_count=len(cards),
        total_ms=_elapsed_ms(pipeline_start),
    )

    return {
        "cards": [c.model_dump() for c in cards],
        "intent": intent.model_dump(),
        "raw_count": len(raw_items),
        "scored_count": len(scored),
        "card_count": len(cards),
    }


# ========== phase 1 意图识别 ==========


async def _phase_intent(
    model,
    *,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> IntentAnalysis:
    """调用模型理解搜索意图，并生成改写查询。"""

    titles_str = ", ".join(existing_titles[:10]) if existing_titles else "(none)"
    user_msg = INTENT_USER_TEMPLATE.format(
        query=query,
        notebook_title=notebook_title or "Untitled",
        article_count=len(existing_titles),
        existing_titles=titles_str,
    )

    try:
        structured_model = model.with_structured_output(IntentAnalysis)
        return await structured_model.ainvoke([
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
    except Exception:
        logger.warning("search_agent.intent_fallback", query=query[:80], exc_info=True)
        return _fallback_intent(query)


def _fallback_intent(query: str) -> IntentAnalysis:
    """当结构化意图生成失败时，使用规则兜底。"""
    return IntentAnalysis(
        intent="explore",
        domain="general",
        facet_weights={
            CoverageFacet.OVERVIEW: 0.8,
            CoverageFacet.AUTHORITATIVE: 0.6,
            CoverageFacet.NOVELTY: 0.5,
            CoverageFacet.RECENT: 0.4,
            CoverageFacet.CRITIQUE: 0.3,
            CoverageFacet.IMPLEMENTATION: 0.3,
            CoverageFacet.PRIMARY: 0.3,
        },
        reformulated_queries=[query],
        time_sensitive=False,
    )


# ========== phase 2 并行召回 ==========


async def _phase_recall(
    *,
    intent: IntentAnalysis,
    query: str,
    exa_api_key: str,
    exa_mode: str,
    max_results: int,
) -> list[RawSearchItem]:
    """对改写查询做多源并行召回。"""

    queries = intent.reformulated_queries or [query]
    recall_queries = queries[:3]
    query_count = max(len(recall_queries), 1)
    # 召回阶段保留适度过采样，避免最终排序前候选过少。
    exa_limit = min(max((max_results * 2 + query_count - 1) // query_count, 4), 20)
    ddg_limit = min(max((max_results + query_count - 1) // query_count, 4), 20)
    news_limit = min(max(max_results // 2, 3), 10)

    tasks: list[tuple[str, Any]] = []

    for q in recall_queries:
        exa_params: dict[str, Any] = {
            "query": q,
            "exa_api_key": exa_api_key,
            "exa_mode": exa_mode,
            "max_results": exa_limit,
        }
        if intent.time_sensitive:
            exa_params["freshness_hours"] = 72
        tasks.append(("exa_search", exa_search.ainvoke(exa_params)))
        tasks.append(("ddg_search", ddg_search.ainvoke({"query": q, "max_results": ddg_limit})))

    tasks.append(("ddg_news", ddg_news.ainvoke({"query": query, "max_results": news_limit})))

    coros = [coro for _, coro in tasks]
    tool_names = [name for name, _ in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)

    items: list[RawSearchItem] = []
    source_counts: dict[str, int] = {}
    for tool_name, result in zip(tool_names, results):
        if isinstance(result, Exception):
            logger.warning(
                "search.recall.tool_error",
                tool=tool_name,
                error=str(result)[:200],
            )
            continue
        parsed = _parse_tool_output(result, tool_name=tool_name)
        items.extend(parsed)
        source_counts[tool_name] = source_counts.get(tool_name, 0) + len(parsed)

    logger.info(
        "search.recall.multi_source_done",
        query_count=len(recall_queries),
        task_count=len(tasks),
        total_items=len(items),
        source_counts=source_counts,
    )
    return items


def _parse_tool_output(raw_result: Any, *, tool_name: str) -> list[RawSearchItem]:
    """把工具返回值归一化为 `RawSearchItem`。"""

    if isinstance(raw_result, dict) and raw_result.get("error"):
        return []

    result_list = raw_result if isinstance(raw_result, list) else [raw_result]
    items: list[RawSearchItem] = []
    for r in result_list:
        if not isinstance(r, dict):
            continue
        url = r.get("url", "").strip()
        if not url:
            continue
        items.append(RawSearchItem(
            title=r.get("title", "").strip() or url,
            url=url,
            description=r.get("description", "").strip(),
            author=r.get("author"),
            published_date=r.get("published_date") or r.get("date"),
            highlights=r.get("highlights", [])[:3],
            source_tool=tool_name,
        ))
    return items


# ========== phase 3 URL 去重 ==========


def _deduplicate(items: list[RawSearchItem]) -> list[RawSearchItem]:
    """按归一化 URL 去重。"""
    seen: set[str] = set()
    deduped: list[RawSearchItem] = []
    for item in items:
        key = _normalize_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip().lower())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# ========== phase 4 打分排序 ==========


async def _phase_score(
    model,
    *,
    candidates: list[RawSearchItem],
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[ScoredItem]:
    """给候选结果打分并排序，优先用 reranker。"""

    if not candidates:
        return []

    from app.infra.ai.reranker import build_reranker

    reranker = build_reranker()
    if reranker:
        scored = await _score_with_reranker(
            reranker,
            candidates=candidates,
            query=query,
            existing_titles=existing_titles,
        )
        if scored:
            return scored
        logger.warning("search_agent.reranker_failed_fallback_to_llm")

    return await _score_with_llm(
        model,
        candidates=candidates,
        intent=intent,
        query=query,
        notebook_title=notebook_title,
        existing_titles=existing_titles,
    )


# ====== step 1 reranker 打分 ======


async def _score_with_reranker(
    reranker,
    *,
    candidates: list[RawSearchItem],
    query: str,
    existing_titles: list[str],
) -> list[ScoredItem] | None:
    """用一次 rerank 请求给全部候选打分。"""

    documents = [
        f"{c.title}\n{c.description}" for c in candidates
    ]

    try:
        results = await reranker.rerank(query=query, documents=documents)
    except Exception as exc:
        logger.warning("search_agent.reranker_error", error=str(exc)[:200])
        return None

    score_by_index = {r.index: r.relevance_score for r in results}
    existing_lower = {t.lower().strip() for t in existing_titles}

    scored: list[ScoredItem] = []
    for i, c in enumerate(candidates):
        rel = score_by_index.get(i, 0.0)
        auth = _authority_heuristic(c.url)
        is_existing = c.title.lower().strip() in existing_lower
        novelty = 0.2 if is_existing else 0.7
        final = rel * 0.70 + auth * 0.20 + novelty * 0.10

        scored.append(ScoredItem(
            title=c.title,
            url=c.url,
            description=c.description,
            author=c.author,
            published_date=c.published_date,
            highlights=c.highlights,
            source_tool=c.source_tool,
            relevance_score=round(rel, 4),
            authority_score=round(auth, 2),
            novelty_score=round(novelty, 2),
            final_score=round(final, 4),
            why_selected=_auto_why(rel, auth, c.source_tool),
        ))

    scored.sort(key=lambda x: x.final_score, reverse=True)
    logger.info(
        "search_agent.reranker_scored",
        candidate_count=len(candidates),
        top_score=scored[0].final_score if scored else 0,
    )
    return scored


_AUTHORITY_PATTERNS: list[tuple[str, float]] = [
    (".edu", 0.90), (".gov", 0.90), (".ac.", 0.85),
    ("arxiv.org", 0.90), ("github.com", 0.80), ("stackoverflow.com", 0.75),
    ("docs.", 0.80), ("developer.", 0.80),
    ("medium.com", 0.55), ("blog", 0.55),
]


def _authority_heuristic(url: str) -> float:
    """按域名模式估算权威性分数。"""
    lower = url.lower()
    for pattern, score in _AUTHORITY_PATTERNS:
        if pattern in lower:
            return score
    return 0.50


def _auto_why(rel: float, auth: float, source_tool: str) -> str:
    parts: list[str] = []
    if rel >= 0.8:
        parts.append("高度相关")
    elif rel >= 0.5:
        parts.append("相关")
    if auth >= 0.8:
        parts.append("权威来源")
    if source_tool:
        parts.append(f"来自 {source_tool}")
    return "，".join(parts) if parts else "搜索结果"


# ====== step 2 LLM 批量打分兜底 ======


async def _score_with_llm(
    model,
    *,
    candidates: list[RawSearchItem],
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[ScoredItem]:
    """兜底路径：用轻量模型分批打分。"""

    all_scored: list[ScoredItem] = []
    batch_size = 15
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        scored = await _llm_score_batch(
            model,
            batch=batch,
            intent=intent,
            query=query,
            notebook_title=notebook_title,
            existing_titles=existing_titles,
        )
        all_scored.extend(scored)

    all_scored.sort(key=lambda x: x.final_score, reverse=True)
    return all_scored


async def _llm_score_batch(
    model,
    *,
    batch: list[RawSearchItem],
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[ScoredItem]:
    """用结构化输出给单批候选结果打分。"""

    weights_json = json.dumps(
        {k.value: v for k, v in intent.facet_weights.items()},
        ensure_ascii=False,
    )
    candidates_json = json.dumps(
        [c.model_dump() for c in batch],
        ensure_ascii=False,
        default=str,
    )
    titles_str = ", ".join(existing_titles[:8]) if existing_titles else "(none)"

    system = SCORER_SYSTEM_PROMPT.format(facet_weights_json=weights_json)
    user = SCORER_USER_TEMPLATE.format(
        query=query,
        notebook_title=notebook_title or "Untitled",
        existing_titles=titles_str,
        candidates_json=candidates_json,
    )

    try:
        structured_model = model.with_structured_output(ScoringOutput)
        response = await structured_model.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])
        return response.scored_items
    except Exception as e:
        logger.warning(
            "search_agent.llm_score_fallback",
            error_type=type(e).__name__,
            error_msg=str(e),
            exc_info=True,
        )
    return [
        ScoredItem(
            title=c.title,
            url=c.url,
            description=c.description,
            author=c.author,
            published_date=c.published_date,
            highlights=c.highlights,
            source_tool=c.source_tool,
            relevance_score=0.5,
            authority_score=0.3,
            novelty_score=0.5,
            final_score=0.4,
            why_selected="auto-scored (LLM unavailable)",
        )
        for c in batch
    ]


# ========== phase 5 组装结果卡片 ==========


def _build_cards(
    scored: list[ScoredItem],
    *,
    existing_urls: set[str],
    max_results: int,
) -> list[SearchCardOut]:
    """把打分结果转换成前端卡片。"""
    cards: list[SearchCardOut] = []

    for rank, item in enumerate(scored[:max_results], start=1):
        url_norm = _normalize_url(item.url)
        is_duplicate = url_norm in {_normalize_url(u) for u in existing_urls}
        domain = urlparse(item.url).netloc

        import_suggestion = "duplicate_risk" if is_duplicate else (
            "recommended" if item.final_score >= 0.6 else "optional"
        )

        authority_badge = None
        if item.authority_score >= 0.8:
            authority_badge = "权威来源"
        elif item.authority_score >= 0.6:
            authority_badge = "知名来源"

        cards.append(SearchCardOut(
            title=item.title,
            url=item.url,
            source_name=domain,
            source_type_badge=_guess_doc_type(item.url, domain),
            published_at=item.published_date,
            authority_badge=authority_badge,
            why_selected=item.why_selected,
            highlights=item.highlights[:2],
            import_suggestion=import_suggestion,
            description=item.description,
            author=item.author,
            final_score=item.final_score,
            display_rank=rank,
        ))

    return cards


def _guess_doc_type(url: str, domain: str) -> str:
    url_lower = url.lower()
    if "arxiv.org" in url_lower:
        return "paper"
    if url_lower.endswith(".pdf"):
        return "pdf"
    if any(d in domain for d in ("github.com", "gitlab.com")):
        return "code"
    if any(d in domain for d in ("docs.", "developer.", "/docs/", "/api/")):
        return "official"
    if any(d in domain for d in (".edu", ".gov", ".ac.")):
        return "academic"
    if "blog" in domain or "medium.com" in domain:
        return "blog"
    if any(d in domain for d in ("news", "reuters", "bbc", "techcrunch")):
        return "news"
    return "web"


def _elapsed_ms(start: float) -> float:
    from time import perf_counter
    return round((perf_counter() - start) * 1000, 2)
