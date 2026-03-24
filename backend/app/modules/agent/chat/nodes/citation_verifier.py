"""Node 6: Citation Verifier + Trace Logger。"""

from __future__ import annotations

from time import perf_counter
from typing import Any

import structlog

from app.infra.telemetry.metrics import (
    observe_chat_citation_count,
    observe_chat_evidence_coverage,
    observe_chat_stage,
)
from app.modules.agent.chat.state import ChatGraphState

logger = structlog.get_logger(__name__)


async def citation_verifier_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    raw_citations = state.get("raw_citations", [])
    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])

    # ========== phase 1 校验引用 ID 是否存在 ==========
    verified: list[dict] = []
    for cite in raw_citations:
        ctype = cite.get("type", "local")
        cid = cite.get("id", 0)

        if ctype == "local":
            if 1 <= cid <= len(local_evidence):
                evidence = local_evidence[cid - 1]
                verified.append({
                    "id": cid,
                    "type": "local",
                    "chunk_id": evidence.get("chunk_id"),
                    "article_id": evidence.get("article_id"),
                    "article_title": evidence.get("article_title", ""),
                    "text_preview": evidence.get("raw_text", "")[:100],
                })
        elif ctype == "web":
            if 1 <= cid <= len(web_evidence):
                evidence = web_evidence[cid - 1]
                verified.append({
                    "id": cid,
                    "type": "web",
                    "url": evidence.get("url", ""),
                    "title": evidence.get("title", ""),
                    "text_preview": evidence.get("snippet", "")[:100],
                })

    # ========== phase 2 构建 trace log ==========
    max_score = 0.0
    if local_evidence:
        max_score = max(e.get("score", 0.0) for e in local_evidence)

    trace_log = {
        "retrieval_top_k": len(local_evidence),
        "rerank_top_score": round(max_score, 4),
        "web_searched": state.get("need_web_search", False),
        "web_search_reason": state.get("web_search_reason", "not_needed"),
        "web_result_count": len(web_evidence),
        "answer_length": len(state.get("answer_text", "")),
        "citation_count": len(verified),
        "invalid_citation_count": len(raw_citations) - len(verified),
        "route": route,
    }

    # ========== phase 3 指标 ==========
    observe_chat_citation_count(route=route, count=len(verified))
    if local_evidence:
        cited_ids = {c["id"] for c in verified if c.get("type") == "local"}
        coverage = len(cited_ids) / len(local_evidence)
        observe_chat_evidence_coverage(route=route, coverage=coverage)

    observe_chat_stage(stage="citation_verifier", route=route, status="ok", duration_ms=_ms(t0))
    logger.info("chat.citation_verified", **trace_log)

    return {
        "verified_citations": verified,
        "trace_log": trace_log,
    }


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
