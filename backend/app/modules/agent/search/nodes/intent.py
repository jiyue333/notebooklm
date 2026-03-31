"""意图分析节点：将用户查询结构化为搜索任务规格（SearchTaskSpec）。"""

from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import Any, Literal

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.infra.telemetry.metrics import observe_search_stage
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search.state import SearchGraphState, SearchQueryPlan, SearchTaskSpec
from app.modules.agent.search.utils import _elapsed_ms, _safe_text

logger = structlog.get_logger(__name__)

_DEFAULT_SCORE_WEIGHTS = {
    "relevance_score": 0.34,
    "authority_score": 0.18,
    "coverage_score": 0.14,
    "freshness_score": 0.14,
    "content_quality_score": 0.12,
    "novelty_score": 0.08,
}
_INTENT_ANALYSIS_TIMEOUT_BY_MODE = {"fast": 8.0, "auto": 12.0, "deep": 15.0}


class _IntentOutput(BaseModel):
    search_type: Literal["opinionated", "objective_fact", "exploratory", "comparison", "primary_source", "news_sensitive"] = "exploratory"
    content_depth: Literal["overview", "detail", "mixed"] = "mixed"
    time_sensitivity: Literal["low", "medium", "high"] = "medium"
    authority_preference: Literal["low", "medium", "high"] = "high"
    novelty_requirement: Literal["low", "medium", "high"] = "medium"
    domain_hint: str = "general"
    query_plans: list[SearchQueryPlan] = Field(default_factory=list)
    score_weights: dict[str, float] = Field(default_factory=dict)


def make_intent_node(model):
    """返回绑定了 *model* 的意图分析 LangGraph 节点函数。"""

    async def intent_analysis_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        with start_span("search.intent_analysis", attributes={"search.mode": mode}):
            task_spec = await _analyze_task_spec(
                model,
                query=state["query"],
                mode=mode,
                notebook_title=state["notebook_title"],
                notebook_summaries=state.get("notebook_article_summaries", []),
            )
            observe_search_stage(stage="intent_analysis", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
            return {"task_spec": task_spec}

    return intent_analysis_node


def build_rewritten_query(query: str) -> str:
    """规则引擎改写 query：清理 site: 前缀、去重复词、标准化空白。"""

    cleaned = re.sub(r"site:\S+", "", query).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query.strip()


async def _analyze_task_spec(
    model,
    *,
    query: str,
    mode: str,
    notebook_title: str,
    notebook_summaries: list[dict[str, str]],
) -> SearchTaskSpec:
    rewritten = build_rewritten_query(query)
    base_spec = _build_rule_task_spec(query, mode=mode, rewritten_query=rewritten)

    if model is None:
        return base_spec

    summary_lines = [
        f"- {_safe_text(item.get('title')) or 'Untitled'}: {_safe_text(item.get('summaryText'))[:160]}"
        for item in notebook_summaries[:8]
        if _safe_text(item.get("summaryText"))
    ]
    user_prompt = "\n".join([
        f"用户问题：{query}",
        f"Notebook 标题：{notebook_title or 'Untitled'}",
        "Notebook 已有摘要：",
        "\n".join(summary_lines) if summary_lines else "(none)",
    ])
    try:
        structured_model = model.with_structured_output(
            _IntentOutput,
            method="function_calling",
        )
        timeout_seconds = _resolve_intent_timeout_seconds(mode)
        llm_t0 = perf_counter()
        output = await asyncio.wait_for(
            structured_model.ainvoke([
                SystemMessage(content=(
                    "你是 research search planner。分析用户问题与 notebook 上下文，输出结构化搜索计划。\n"
                    "请明确 search_type、content_depth、time_sensitivity。\n"
                    "生成恰好 4 条 query_plans，每条从不同角度搜索（如 authority、overview、detail、novelty），"
                    "query 应是可直接发给搜索引擎的完整搜索语句。\n"
                    "score_weights 只输出 relevance_score、authority_score、coverage_score、"
                    "freshness_score、content_quality_score、novelty_score 六项权重，值在 0-1。\n"
                    "注意：不需要输出 rewritten_query。"
                )),
                HumanMessage(content=user_prompt),
            ]),
            timeout=timeout_seconds,
        )
        llm_ms = _elapsed_ms(llm_t0)
        plans = output.query_plans[:4] if output.query_plans else []
        logger.info(
            "search.intent_llm_done",
            mode=mode,
            duration_ms=llm_ms,
            search_type=output.search_type,
            plan_count=len(plans),
        )
        return SearchTaskSpec(
            search_type=output.search_type,
            content_depth=output.content_depth,
            time_sensitivity=output.time_sensitivity,
            authority_preference=output.authority_preference,
            novelty_requirement=output.novelty_requirement,
            domain_hint=output.domain_hint,
            rewritten_query=rewritten,
            query_plans=plans or base_spec.query_plans,
            score_weights=_normalize_weights(output.score_weights or _DEFAULT_SCORE_WEIGHTS),
        )
    except TimeoutError:
        logger.warning(
            "search.intent_analysis_timeout",
            mode=mode,
            timeout_seconds=_resolve_intent_timeout_seconds(mode),
            duration_ms=_elapsed_ms(llm_t0),
        )
        return base_spec
    except Exception:
        logger.warning("search.intent_analysis_fallback", duration_ms=_elapsed_ms(llm_t0), exc_info=True)
        return base_spec


def _build_rule_task_spec(query: str, *, mode: str = "auto", rewritten_query: str = "") -> SearchTaskSpec:
    """纯规则构建 TaskSpec，rewritten_query 由外部传入。"""

    lowered = query.lower()
    if any(keyword in lowered for keyword in ["对比", "比较", "vs", "versus", "compare"]):
        search_type = "comparison"
    elif any(keyword in lowered for keyword in ["新闻", "latest", "today", "breaking", "动态"]):
        search_type = "news_sensitive"
    elif any(keyword in lowered for keyword in ["是什么", "what is", "define", "定义"]):
        search_type = "objective_fact"
    else:
        search_type = "exploratory"
    content_depth = "detail" if any(keyword in lowered for keyword in ["深入", "detail", "原理", "实现"]) else "mixed"
    high_time_signals = ["最新", "today", "newest", "近期", "最近", "本周", "本月"]
    has_year_hint = bool(re.search(r"\b20\d{2}\b", lowered))
    time_sensitivity = "high" if has_year_hint or any(keyword in lowered for keyword in high_time_signals) else "medium"
    if mode == "fast":
        content_depth = "overview"
    elif mode == "deep" and content_depth == "mixed":
        content_depth = "detail"
    return SearchTaskSpec(
        search_type=search_type,
        content_depth=content_depth,
        time_sensitivity=time_sensitivity,
        authority_preference="high",
        novelty_requirement="medium",
        domain_hint="general",
        rewritten_query=rewritten_query or query,
        query_plans=_build_rule_query_plans(
            rewritten_query or query,
            search_type=search_type,
            time_sensitivity=time_sensitivity,
        ),
        score_weights=_default_weights_for(search_type, time_sensitivity),
    )


def _build_rule_query_plans(
    query: str,
    *,
    search_type: str = "exploratory",
    time_sensitivity: str = "medium",
) -> list[SearchQueryPlan]:
    """规则引擎生成 4 条 query_plans 作为 fallback。"""

    normalized = _safe_text(query)
    plans = [
        SearchQueryPlan(key="authority", query=f"{normalized} official documentation reference".strip(), intent="authority"),
        SearchQueryPlan(key="overview", query=f"{normalized} overview key concepts explained".strip(), intent="overview"),
    ]
    if search_type == "comparison":
        plans.append(SearchQueryPlan(key="compare", query=f"{normalized} comparison benchmark pros cons".strip(), intent="comparison"))
    else:
        plans.append(SearchQueryPlan(key="detail", query=f"{normalized} detailed implementation examples".strip(), intent="detail"))
    if time_sensitivity == "high":
        plans.append(SearchQueryPlan(key="fresh", query=f"{normalized} latest updates 2026".strip(), intent="fresh"))
    else:
        plans.append(SearchQueryPlan(key="novel", query=f"{normalized} case study practical lessons".strip(), intent="novelty"))
    return plans[:4]


# keep old name as alias for external imports
_fallback_task_spec = _build_rule_task_spec
_fallback_query_plans = _build_rule_query_plans


def _resolve_intent_timeout_seconds(mode: str) -> float:
    return float(_INTENT_ANALYSIS_TIMEOUT_BY_MODE.get(mode, 6.0))


def _default_weights_for(search_type: str, time_sensitivity: str) -> dict[str, float]:
    weights = dict(_DEFAULT_SCORE_WEIGHTS)
    if search_type == "opinionated":
        weights["coverage_score"] += 0.06
        weights["novelty_score"] += 0.04
    if search_type == "objective_fact":
        weights["authority_score"] += 0.06
        weights["coverage_score"] -= 0.03
    if time_sensitivity == "high":
        weights["freshness_score"] += 0.1
        weights["authority_score"] -= 0.03
    return _normalize_weights(weights)


def _normalize_weights(raw: dict[str, float]) -> dict[str, float]:
    filtered = {
        key: max(float(value), 0.0)
        for key, value in raw.items()
        if key in _DEFAULT_SCORE_WEIGHTS
    }
    merged = {**_DEFAULT_SCORE_WEIGHTS, **filtered}
    total = sum(merged.values()) or 1.0
    return {key: round(value / total, 4) for key, value in merged.items()}
