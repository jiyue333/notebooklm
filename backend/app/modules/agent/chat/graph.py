"""Chat LangGraph 编排。

flow: query_router → retrieval_planner → [retrieval_engine | skip] → web_search_broker
      → answer_generator → citation_verifier → END
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.modules.agent.chat.nodes import (
    answer_generator_node,
    citation_verifier_node,
    query_router_node,
    retrieval_engine_node,
    retrieval_planner_node,
    web_search_broker_node,
)
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec


def _should_retrieve(state: ChatGraphState) -> Literal["retrieve", "skip"]:
    plan: RetrievalPlanSpec = state.get("retrieval_plan", RetrievalPlanSpec())
    if plan.strategy == "skip":
        return "skip"
    return "retrieve"


def build_chat_graph() -> Any:
    builder = StateGraph(ChatGraphState)

    builder.add_node("query_router", query_router_node)
    builder.add_node("retrieval_planner", retrieval_planner_node)
    builder.add_node("retrieval_engine", retrieval_engine_node)
    builder.add_node("web_search_broker", web_search_broker_node)
    builder.add_node("answer_generator", answer_generator_node)
    builder.add_node("citation_verifier", citation_verifier_node)

    builder.add_edge(START, "query_router")
    builder.add_edge("query_router", "retrieval_planner")
    builder.add_conditional_edges("retrieval_planner", _should_retrieve, {
        "retrieve": "retrieval_engine",
        "skip": "web_search_broker",
    })
    builder.add_edge("retrieval_engine", "web_search_broker")
    builder.add_edge("web_search_broker", "answer_generator")
    builder.add_edge("answer_generator", "citation_verifier")
    builder.add_edge("citation_verifier", END)

    return builder.compile()


_graph = None


def get_chat_graph():
    global _graph
    if _graph is None:
        _graph = build_chat_graph()
    return _graph
