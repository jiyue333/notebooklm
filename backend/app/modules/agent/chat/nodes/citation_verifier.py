"""Node 6: Citation Verifier + Trace Logger。"""

from __future__ import annotations

import re
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
    answer_text = str(state.get("answer_text") or "")
    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])

    # ========== phase 1 校验引用 ID 是否存在 + claim 覆盖 ==========
    claim_windows = _extract_claim_windows(answer_text)
    support_map = _score_citation_support(
        claim_windows=claim_windows,
        local_evidence=local_evidence,
        web_evidence=web_evidence,
    )
    verified: list[dict] = []
    supported_local_ids: set[int] = set()
    supported_web_ids: set[int] = set()
    for cite in raw_citations:
        ctype = cite.get("type", "local")
        cid = cite.get("id", 0)
        support_score = float(support_map.get((ctype, cid), 0.0))
        is_supported = support_score >= 0.12

        if ctype == "local":
            if 1 <= cid <= len(local_evidence) and is_supported:
                evidence = local_evidence[cid - 1]
                verified.append({
                    "id": cid,
                    "type": "local",
                    "chunk_id": evidence.get("chunk_id"),
                    "article_id": evidence.get("article_id"),
                    "article_title": evidence.get("article_title", ""),
                    "text_preview": evidence.get("raw_text", "")[:100],
                    "support_score": round(support_score, 4),
                })
                supported_local_ids.add(cid)
        elif ctype == "web":
            if 1 <= cid <= len(web_evidence) and is_supported:
                evidence = web_evidence[cid - 1]
                verified.append({
                    "id": cid,
                    "type": "web",
                    "url": evidence.get("url", ""),
                    "title": evidence.get("title", ""),
                    "text_preview": evidence.get("snippet", "")[:100],
                    "support_score": round(support_score, 4),
                })
                supported_web_ids.add(cid)

    rewritten_answer = _rewrite_answer_citations(
        answer_text=answer_text,
        keep_local_ids=supported_local_ids,
        keep_web_ids=supported_web_ids,
    )
    local_coverage = len(supported_local_ids) / max(len(local_evidence), 1) if local_evidence else 0.0

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
        "answer_length": len(rewritten_answer),
        "citation_count": len(verified),
        "invalid_citation_count": len(raw_citations) - len(verified),
        "citation_local_coverage": round(local_coverage, 4),
        "citation_claim_supported": round(
            len(verified) / max(len(raw_citations), 1),
            4,
        ) if raw_citations else 1.0,
        "citation_low_coverage": bool(raw_citations and local_coverage < 0.2),
        "route": route,
    }

    # ========== phase 3 指标 ==========
    observe_chat_citation_count(route=route, count=len(verified))
    if local_evidence:
        observe_chat_evidence_coverage(route=route, coverage=local_coverage)

    observe_chat_stage(stage="citation_verifier", route=route, status="ok", duration_ms=_ms(t0))
    logger.info("chat.citation_verified", **trace_log)

    return {
        "verified_citations": verified,
        "answer_text": rewritten_answer,
        "trace_log": trace_log,
    }


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _extract_claim_windows(text: str) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    if not text:
        return windows
    for match in re.finditer(r"\[(W?)(\d+)\]", text):
        ctype = "web" if match.group(1) else "local"
        cid = int(match.group(2))
        start = max(match.start() - 120, 0)
        end = min(match.end() + 120, len(text))
        windows.append({
            "type": ctype,
            "id": cid,
            "context": text[start:end],
        })
    return windows


def _score_citation_support(
    *,
    claim_windows: list[dict[str, Any]],
    local_evidence: list[dict],
    web_evidence: list[dict],
) -> dict[tuple[str, int], float]:
    scores: dict[tuple[str, int], float] = {}
    for item in claim_windows:
        ctype = str(item.get("type") or "local")
        cid = int(item.get("id") or 0)
        context = str(item.get("context") or "")
        if cid <= 0 or not context:
            continue
        evidence_text = ""
        if ctype == "local" and 1 <= cid <= len(local_evidence):
            evidence_text = str(local_evidence[cid - 1].get("raw_text") or "")
        if ctype == "web" and 1 <= cid <= len(web_evidence):
            evidence = web_evidence[cid - 1]
            evidence_text = " ".join([
                str(evidence.get("title") or ""),
                str(evidence.get("snippet") or ""),
            ])
        if not evidence_text:
            continue
        score = _token_overlap_ratio(context, evidence_text)
        marker = (ctype, cid)
        scores[marker] = max(scores.get(marker, 0.0), score)
    return scores


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9]{2,}", left.lower()))
    right_tokens = set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9]{2,}", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(left_tokens)


def _rewrite_answer_citations(
    *,
    answer_text: str,
    keep_local_ids: set[int],
    keep_web_ids: set[int],
) -> str:
    local_new_ids = {old: idx for idx, old in enumerate(sorted(keep_local_ids), start=1)}
    web_new_ids = {old: idx for idx, old in enumerate(sorted(keep_web_ids), start=1)}

    def _replace(match: re.Match[str]) -> str:
        marker_type = "web" if match.group(1) else "local"
        old_id = int(match.group(2))
        if marker_type == "local":
            new_id = local_new_ids.get(old_id)
            return f"[{new_id}]" if new_id is not None else ""
        new_id = web_new_ids.get(old_id)
        return f"[W{new_id}]" if new_id is not None else ""

    rewritten = re.sub(r"\[(W?)(\d+)\]", _replace, answer_text)
    rewritten = re.sub(r"\s{2,}", " ", rewritten)
    rewritten = re.sub(r"\s+([，。！？；、])", r"\1", rewritten)
    return rewritten.strip()
