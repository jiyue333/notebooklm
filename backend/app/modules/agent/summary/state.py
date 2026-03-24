"""Summary graph state 定义。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class SummaryGraphState(TypedDict):
    # ---- 输入 ----
    article_id: str
    title: str
    clean_markdown: str
    language: str
    user: Any

    # ---- Phase 1: analyze ----
    article_type: str          # research | news | tutorial | code_heavy | general
    content_stats: dict        # {token_count, code_ratio, table_count, image_count}
    model_tier: str            # lite | standard

    # ---- Phase 2: compress ----
    compressed_content: str

    # ---- Phase 3: summarize (direct / map-reduce) ----
    map_chunks: list[str]
    chunk_summaries: Annotated[list[str], operator.add]
    summary_text: str

    # ---- Phase 4: validate ----
    validation_passed: bool
    validation_issues: list[str]
    retry_count: int
