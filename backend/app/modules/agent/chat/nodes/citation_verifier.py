"""Node 6: Citation Verifier + Trace Logger."""

from __future__ import annotations

from difflib import SequenceMatcher
import re
from time import perf_counter
from typing import Any

import structlog

from app.infra.ai.reranker import build_reranker
from app.infra.telemetry.metrics import (
    observe_chat_citation_count,
    observe_chat_evidence_coverage,
    observe_chat_stage,
)
from app.modules.agent.chat.state import ChatGraphState

logger = structlog.get_logger(__name__)

_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;\n])")
_CITATION_RE = re.compile(r"\[(W?)(\d+)\]")
_CITATION_ONLY_RE = re.compile(r"^(?:\s*\[(?:W?\d+)\]\s*)+$")
_WEB_SENTINEL = 100_000
_SUPPORT_THRESHOLD = 0.18


async def citation_verifier_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    raw_citations = state.get("raw_citations", [])
    answer_text = str(state.get("answer_text") or "")
    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])
    notebook_id = str(state.get("notebook_id") or "")

    claims = _extract_claims(answer_text)
    support_map = await _score_claim_support(
        claims=claims,
        local_evidence=local_evidence,
        web_evidence=web_evidence,
    )
    claim_debug_rows = _build_claim_debug_rows(
        claims=claims,
        support_map=support_map,
        local_evidence=local_evidence,
        web_evidence=web_evidence,
    )

    verified: list[dict[str, Any]] = []
    supported_local_ids: set[int] = set()
    supported_web_ids: set[int] = set()
    supported_claim_count = 0
    unsupported_claim_count = 0
    rewritten_segments: list[str] = []

    for claim in claims:
        text = str(claim.get("text") or "").strip()
        citations = list(claim.get("citations") or [])
        if not text:
            continue

        # Keep short connective lines only when they don't assert facts.
        if not citations:
            if len(text) <= 16 and re.fullmatch(r"[一-龥A-Za-z0-9：:、\-\s]+", text):
                rewritten_segments.append(text)
            continue

        kept_citations: list[dict[str, Any]] = []
        for cite in citations:
            ctype = str(cite.get("type") or "local")
            cid = int(cite.get("id") or 0)
            support_score = float(support_map.get((id(claim), ctype, cid), 0.0))
            is_supported = support_score >= _SUPPORT_THRESHOLD
            if not is_supported:
                continue

            evidence = _get_evidence(ctype=ctype, cid=cid, local_evidence=local_evidence, web_evidence=web_evidence)
            if evidence is None:
                continue

            payload: dict[str, Any] = {
                "id": cid,
                "type": ctype,
                "support_score": round(support_score, 4),
            }
            if ctype == "web":
                payload.update({
                    "url": evidence.get("url", ""),
                    "title": evidence.get("title", ""),
                    "text_preview": evidence.get("snippet", "")[:160],
                    "locator_text": evidence.get("snippet", "")[:240],
                })
                supported_web_ids.add(cid)
            else:
                payload.update({
                    "chunk_id": evidence.get("chunk_id"),
                    "chunk_index": evidence.get("chunk_index"),
                    "article_id": evidence.get("article_id"),
                    "article_title": evidence.get("article_title", ""),
                    "notebook_id": notebook_id,
                    "section_path": evidence.get("section_path"),
                    "heading_title": evidence.get("heading_title"),
                    "text_preview": evidence.get("raw_text", "")[:160],
                    "locator_text": evidence.get("locator_text") or evidence.get("raw_text", "")[:240],
                    "title": evidence.get("article_title", ""),
                })
                supported_local_ids.add(cid)

            kept_citations.append(payload)

            if not any(
                existing.get("type") == ctype and int(existing.get("id") or 0) == cid
                for existing in verified
            ):
                verified.append(payload)

        if not kept_citations:
            unsupported_claim_count += 1
            continue

        supported_claim_count += 1
        rewritten_segments.append(_rewrite_claim_text(text, kept_citations))

    rewritten_answer, local_new_ids, web_new_ids = _rewrite_answer_citations(
        answer_text="\n".join(rewritten_segments),
        keep_local_ids=supported_local_ids,
        keep_web_ids=supported_web_ids,
    )
    if not rewritten_answer:
        if answer_text.strip() and not raw_citations:
            rewritten_answer = answer_text.strip()
        else:
            rewritten_answer = "根据当前检索到的证据，暂时无法确认一个可靠答案。"
        logger.warning(
            "chat.citation_verifier_fallback_answer",
            route=route,
            original_answer_preview=answer_text[:500],
            claim_debug=claim_debug_rows[:8],
        )

    for item in verified:
        ctype = str(item.get("type") or "local")
        original_id = int(item.get("id") or 0)
        display_index = local_new_ids.get(original_id) if ctype == "local" else web_new_ids.get(original_id)
        if display_index is None:
            continue
        item["display_index"] = display_index
        item["citation_label"] = f"[W{display_index}]" if ctype == "web" else f"[{display_index}]"

    local_coverage = len(supported_local_ids) / max(len(local_evidence), 1) if local_evidence else 0.0
    claim_count = len([claim for claim in claims if claim.get("citations")])

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
        "invalid_citation_count": max(len(raw_citations) - len(verified), 0),
        "citation_local_coverage": round(local_coverage, 4),
        "claim_count": claim_count,
        "supported_claim_count": supported_claim_count,
        "unsupported_claim_count": unsupported_claim_count,
        "claim_coverage": round(supported_claim_count / max(claim_count, 1), 4) if claim_count else 1.0,
        "citation_precision": round(len(verified) / max(len(raw_citations), 1), 4) if raw_citations else 1.0,
        "citation_low_coverage": bool(raw_citations and local_coverage < 0.2),
        "route": route,
    }

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


def _extract_claims(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    segments = [segment.strip() for segment in _SENTENCE_END_RE.split(text) if segment.strip()]
    claims: list[dict[str, Any]] = []
    for segment in segments:
        if _CITATION_ONLY_RE.fullmatch(segment):
            if not claims:
                continue
            prior_text = str(claims[-1].get("text") or "").rstrip()
            claims[-1]["text"] = f"{prior_text}{segment}"
            claims[-1]["citations"] = [
                {"type": "web" if match.group(1) else "local", "id": int(match.group(2))}
                for match in _CITATION_RE.finditer(str(claims[-1]["text"]))
            ]
            continue
        citations = [
            {"type": "web" if match.group(1) else "local", "id": int(match.group(2))}
            for match in _CITATION_RE.finditer(segment)
        ]
        claims.append({
            "text": segment,
            "citations": citations,
        })
    return claims


async def _score_claim_support(
    *,
    claims: list[dict[str, Any]],
    local_evidence: list[dict],
    web_evidence: list[dict],
) -> dict[tuple[int, str, int], float]:
    reranker = build_reranker()
    support_map: dict[tuple[int, str, int], float] = {}

    for claim in claims:
        text = _strip_citation_markers(str(claim.get("text") or "")).strip()
        citations = list(claim.get("citations") or [])
        if not text or not citations:
            continue

        docs: list[str] = []
        markers: list[tuple[str, int]] = []
        for cite in citations:
            ctype = str(cite.get("type") or "local")
            cid = int(cite.get("id") or 0)
            evidence = _get_evidence(ctype=ctype, cid=cid, local_evidence=local_evidence, web_evidence=web_evidence)
            if evidence is None:
                continue
            doc = str(evidence.get("evidence_text") or evidence.get("raw_text") or evidence.get("snippet") or "").strip()
            if not doc:
                continue
            docs.append(doc[:1200])
            markers.append((ctype, cid))

        if not docs:
            continue

        if reranker is None:
            for marker, doc in zip(markers, docs, strict=False):
                support_map[(id(claim), marker[0], marker[1])] = _lexical_support_score(text, doc)
            continue

        try:
            results = await reranker.rerank(text, docs, top_n=len(docs))
        except Exception:
            for marker, doc in zip(markers, docs, strict=False):
                support_map[(id(claim), marker[0], marker[1])] = _lexical_support_score(text, doc)
            continue

        rerank_scores = {
            markers[item.index]: float(item.relevance_score)
            for item in results
            if 0 <= item.index < len(markers)
        }

        for marker, doc in zip(markers, docs, strict=False):
            lexical_score = _lexical_support_score(text, doc)
            rerank_score = rerank_scores.get(marker, 0.0)
            support_map[(id(claim), marker[0], marker[1])] = max(rerank_score, lexical_score)

    return support_map


def _get_evidence(
    *,
    ctype: str,
    cid: int,
    local_evidence: list[dict],
    web_evidence: list[dict],
) -> dict[str, Any] | None:
    if ctype == "web":
        if 1 <= cid <= len(web_evidence):
            return web_evidence[cid - 1]
        return None
    if 1 <= cid <= len(local_evidence):
        return local_evidence[cid - 1]
    return None


def _rewrite_claim_text(text: str, citations: list[dict[str, Any]]) -> str:
    cleaned = _strip_citation_markers(text).strip()
    ordered_markers: list[str] = []
    seen: set[int] = set()
    for cite in citations:
        ctype = str(cite.get("type") or "local")
        cid = int(cite.get("id") or 0)
        key = cid if ctype == "local" else cid + _WEB_SENTINEL
        if key in seen or cid <= 0:
            continue
        seen.add(key)
        ordered_markers.append(f"[W{cid}]" if ctype == "web" else f"[{cid}]")
    suffix = "".join(ordered_markers)
    if not suffix:
        return cleaned
    spacer = "" if cleaned.endswith(("：", ":")) else " "
    return f"{cleaned}{spacer}{suffix}".strip()


def _strip_citation_markers(text: str) -> str:
    stripped = _CITATION_RE.sub("", text)
    stripped = re.sub(r"\s{2,}", " ", stripped)
    stripped = re.sub(r"\s+([，。！？；、])", r"\1", stripped)
    return stripped.strip()


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9]{2,}", left.lower()))
    right_tokens = set(re.findall(r"[\u4e00-\u9fff]{1,}|[a-zA-Z0-9]{2,}", right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0.0
    return len(overlap) / len(left_tokens)


def _lexical_support_score(claim: str, evidence: str) -> float:
    token_score = _token_overlap_ratio(claim, evidence)
    char_score = _cjk_ngram_overlap_ratio(claim, evidence)
    sequence_score = _sequence_recall_ratio(claim, evidence)
    return max(token_score, char_score, sequence_score)


def _cjk_ngram_overlap_ratio(left: str, right: str, *, n: int = 2) -> float:
    left_ngrams = _cjk_ngrams(left, n=n)
    right_ngrams = _cjk_ngrams(right, n=n)
    if not left_ngrams or not right_ngrams:
        return 0.0
    overlap = left_ngrams & right_ngrams
    if not overlap:
        return 0.0
    return len(overlap) / len(left_ngrams)


def _cjk_ngrams(text: str, *, n: int) -> set[str]:
    normalized = "".join(re.findall(r"[\u4e00-\u9fff]+", text))
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i:i + n] for i in range(len(normalized) - n + 1)}


def _sequence_recall_ratio(claim: str, evidence: str) -> float:
    left = _normalize_sequence_text(claim)
    right = _normalize_sequence_text(evidence)
    if not left or not right:
        return 0.0
    matcher = SequenceMatcher(a=left, b=right, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / max(len(left), 1)


def _normalize_sequence_text(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text.lower()))


def _rewrite_answer_citations(
    *,
    answer_text: str,
    keep_local_ids: set[int],
    keep_web_ids: set[int],
) -> tuple[str, dict[int, int], dict[int, int]]:
    local_new_ids: dict[int, int] = {}
    web_new_ids: dict[int, int] = {}

    for match in _CITATION_RE.finditer(answer_text):
        marker_type = "web" if match.group(1) else "local"
        old_id = int(match.group(2))
        if marker_type == "local":
            if old_id not in keep_local_ids or old_id in local_new_ids:
                continue
            local_new_ids[old_id] = len(local_new_ids) + 1
            continue
        if old_id not in keep_web_ids or old_id in web_new_ids:
            continue
        web_new_ids[old_id] = len(web_new_ids) + 1

    def _replace(match: re.Match[str]) -> str:
        marker_type = "web" if match.group(1) else "local"
        old_id = int(match.group(2))
        if marker_type == "local":
            new_id = local_new_ids.get(old_id)
            return f"[{new_id}]" if new_id is not None else ""
        new_id = web_new_ids.get(old_id)
        return f"[W{new_id}]" if new_id is not None else ""

    rewritten = _CITATION_RE.sub(_replace, answer_text)
    rewritten = re.sub(r"\s{2,}", " ", rewritten)
    rewritten = re.sub(r"\s+([，。！？；、])", r"\1", rewritten)
    return rewritten.strip(), local_new_ids, web_new_ids


def _build_claim_debug_rows(
    *,
    claims: list[dict[str, Any]],
    support_map: dict[tuple[int, str, int], float],
    local_evidence: list[dict],
    web_evidence: list[dict],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for claim in claims:
        text = _strip_citation_markers(str(claim.get("text") or "")).strip()
        citations = list(claim.get("citations") or [])
        if not text:
            continue
        citation_rows: list[dict[str, Any]] = []
        for cite in citations:
            ctype = str(cite.get("type") or "local")
            cid = int(cite.get("id") or 0)
            evidence = _get_evidence(ctype=ctype, cid=cid, local_evidence=local_evidence, web_evidence=web_evidence)
            citation_rows.append({
                "type": ctype,
                "id": cid,
                "score": round(float(support_map.get((id(claim), ctype, cid), 0.0)), 4),
                "evidence_preview": str(
                    (evidence or {}).get("evidence_text")
                    or (evidence or {}).get("raw_text")
                    or (evidence or {}).get("snippet")
                    or ""
                )[:220],
            })
        rows.append({
            "claim": text[:260],
            "citations": citation_rows,
        })
    return rows
