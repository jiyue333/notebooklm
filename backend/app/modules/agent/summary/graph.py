"""Summary LangGraph 编排。

flow: analyze → compress → [direct_summarize | map→reduce] → validate → [END | retry]
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.core.config import get_settings
from app.modules.agent.summary.nodes import (
    analyze_content,
    compress_content_node,
    direct_summarize,
    map_split,
    map_summarize,
    reduce_summarize,
    validate_summary,
)
from app.modules.agent.summary.state import SummaryGraphState


def _route_by_strategy(state: SummaryGraphState) -> Literal["direct_summarize", "map_split"]:
    settings = get_settings()
    strategy = (state.get("summary_strategy") or "").strip().lower()
    if strategy == "map_reduce":
        return "map_split"
    token_count = int(state.get("content_stats", {}).get("token_count", 0) or 0)
    if token_count > int(settings.summary_map_reduce_threshold_tokens):
        return "map_split"
    return "direct_summarize"


def _fan_out_map(state: SummaryGraphState) -> list[Send]:
    chunks = state.get("map_chunks", [])
    if not chunks:
        return [Send("reduce_summarize", state)]
    return [Send("map_summarize", {**state, "subject": chunk}) for chunk in chunks]


def _check_validation(state: SummaryGraphState) -> Literal["end", "retry"]:
    if state.get("validation_passed", True):
        return "end"
    settings = get_settings()
    if state.get("retry_count", 0) >= settings.summary_max_retries:
        return "end"
    return "retry"


def _route_retry_target(state: SummaryGraphState) -> Literal["direct_summarize", "reduce_summarize"]:
    strategy = (state.get("summary_strategy") or "").strip().lower()
    if strategy == "map_reduce" and state.get("chunk_summaries"):
        return "reduce_summarize"
    return "direct_summarize"


def build_summary_graph() -> Any:
    builder = StateGraph(SummaryGraphState)

    builder.add_node("analyze_content", analyze_content)
    builder.add_node("compress_content", compress_content_node)
    builder.add_node("direct_summarize", direct_summarize)
    builder.add_node("map_split", map_split)
    builder.add_node("map_summarize", map_summarize)
    builder.add_node("reduce_summarize", reduce_summarize)
    builder.add_node("validate_summary", validate_summary)

    builder.add_edge(START, "analyze_content")
    builder.add_edge("analyze_content", "compress_content")
    builder.add_conditional_edges("compress_content", _route_by_strategy)
    builder.add_conditional_edges("map_split", _fan_out_map, ["map_summarize", "reduce_summarize"])
    builder.add_edge("map_summarize", "reduce_summarize")
    builder.add_edge("reduce_summarize", "validate_summary")
    builder.add_edge("direct_summarize", "validate_summary")
    builder.add_conditional_edges("validate_summary", _check_validation, {"end": END, "retry": "retry_router"})
    builder.add_node("retry_router", lambda state: state)
    builder.add_conditional_edges("retry_router", _route_retry_target)

    return builder.compile()


_graph = None


def get_summary_graph():
    global _graph
    if _graph is None:
        _graph = build_summary_graph()
    return _graph
