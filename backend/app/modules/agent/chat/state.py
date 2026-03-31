"""Chat graph state 定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


@dataclass(slots=True)
class RetrievalPlanSpec:
    strategy: str = "skip"          # chunk_only | article_then_chunk | hybrid | skip
    target_article_ids: list[str] = field(default_factory=list)
    dense_top_k: int = 15
    sparse_top_k: int = 15
    use_rerank: bool = True
    rerank_top_n: int = 8


class ChatGraphState(TypedDict):
    # ---- 输入 ----
    query: str
    notebook_id: str
    article_id: str | None
    user_id: str
    user: Any
    notebook_title: str
    article_title: str
    history: list[dict]
    rolling_summary: str
    recent_highlights: list[dict]
    custom_system_prompt: str
    answer_length_preference: str
    output_language: str
    notebook_article_count: int
    notebook_indexed_article_count: int
    deadline_monotonic: float
    db: Any

    # ---- Query Router 输出 ----
    route: str                          # article_qa | notebook_search | recommendation | general
    retrieval_scope: str                # article | notebook | none
    output_mode: str                    # concise | detailed | list
    tools_needed: list[str]
    router_need_web_search: bool
    router_web_search_reason: str

    # ---- Retrieval Planner 输出 ----
    retrieval_plan: RetrievalPlanSpec

    # ---- Retrieval Engine 输出 ----
    local_evidence: list[dict]

    # ---- Web Search Broker 输出 ----
    need_web_search: bool
    web_search_reason: str
    web_evidence: list[dict]

    # ---- Answer Generator 输出 ----
    answer_text: str
    raw_citations: list[dict]

    # ---- Citation Verifier 输出 ----
    verified_citations: list[dict]
    trace_log: dict
