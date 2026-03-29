from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse


@dataclass(slots=True)
class JudgeResult:
    score: float
    subscores: dict[str, float]
    passed: bool
    reason: str
    details: dict[str, Any]


_EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "about",
    "into",
    "from",
    "that",
    "this",
    "what",
    "why",
    "how",
    "are",
    "was",
    "were",
    "you",
    "your",
    "our",
    "vs",
    "in",
    "on",
    "of",
    "to",
    "a",
    "an",
    "site",
}
_ZH_STOPWORDS = {
    "关于",
    "一些",
    "以及",
    "怎么",
    "如何",
    "哪些",
    "什么",
    "研究",
    "文章",
    "相关",
    "最新",
    "一个",
    "这个",
    "那个",
}
_AUTHORITY_HIGH_PATTERNS = (
    ".gov",
    ".edu",
    "arxiv.org",
    "acm.org",
    "ieee.org",
    "nature.com",
    "science.org",
    "springer.com",
    "elsevier.com",
    "wiley.com",
    "nih.gov",
    "who.int",
)
_AUTHORITY_OFFICIAL_PATTERNS = (
    "langchain.com",
    "llamaindex.ai",
    "openai.com",
    "anthropic.com",
    "python.org",
    "pytorch.org",
    "huggingface.co",
    "github.com",
    "docs.",
    "europa.eu",
    "eur-lex.europa.eu",
    "ec.europa.eu",
)
_AUTHORITY_MEDIUM_PATTERNS = (
    "wikipedia.org",
    "reuters.com",
    "bbc.com",
    "nytimes.com",
    "forbes.com",
    "techcrunch.com",
    "cloud.tencent.com",
    "csdn.net",
    "juejin.cn",
    "medium.com",
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(value, 4)))


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.fmean(values))


def _tokenize_query(text: str) -> list[str]:
    if not text:
        return []
    lowered = text.lower()
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9]{2,}", lowered)
    filtered: list[str] = []
    for term in terms:
        if term in _EN_STOPWORDS or term in _ZH_STOPWORDS:
            continue
        if term.isdigit() and len(term) == 4 and term.startswith("20"):
            continue
        if term in {"com", "org", "net", "ai", "cn", "eu", "www"}:
            continue
        filtered.append(term)
    deduped: list[str] = []
    seen: set[str] = set()
    for term in filtered:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _extract_year(text: str) -> int | None:
    matches = re.findall(r"(20\d{2})", text)
    if not matches:
        return None
    try:
        return max(int(item) for item in matches)
    except ValueError:
        return None


def _score_domain_authority(domain: str) -> float:
    domain = (domain or "").lower().strip()
    if not domain:
        return 0.25
    if any(pattern in domain for pattern in _AUTHORITY_HIGH_PATTERNS):
        return 0.95
    if any(pattern in domain for pattern in _AUTHORITY_OFFICIAL_PATTERNS):
        return 0.82
    if any(pattern in domain for pattern in _AUTHORITY_MEDIUM_PATTERNS):
        return 0.65
    if "." in domain and len(domain.split(".")) >= 2:
        return 0.48
    return 0.35


def _score_relevance_item(query_terms: list[str], text_blob: str) -> float:
    if not query_terms:
        return 0.65
    blob = text_blob.lower()
    hit_count = sum(1 for term in query_terms if term in blob)
    ratio = hit_count / len(query_terms)
    density_bonus = min(len(query_terms) / 10.0, 1.0) * 0.08
    score = 0.20 + ratio * 0.72 + density_bonus
    if hit_count <= 1:
        score = min(score, 0.45)
    if ratio >= 0.9:
        score = min(score, 0.95)
    return _clamp01(score)


def _score_freshness_item(item: dict[str, Any], text_blob: str) -> float:
    now_year = datetime.now(UTC).year
    published_at = str(item.get("publishedAt") or "").strip()
    if published_at:
        parsed = re.search(r"(20\d{2})", published_at)
        if parsed:
            age = max(0, now_year - int(parsed.group(1)))
            if age <= 1:
                return 1.0
            if age <= 2:
                return 0.85
            if age <= 4:
                return 0.65
            return 0.45
    extracted_year = _extract_year(text_blob)
    if extracted_year is not None:
        age = max(0, now_year - extracted_year)
        if age <= 1:
            return 0.9
        if age <= 2:
            return 0.78
        if age <= 4:
            return 0.62
        return 0.45
    if item.get("highlights") or item.get("why_selected"):
        return 0.5
    return 0.32


def _score_content_quality_item(title: str, highlights: str, why_selected: str) -> float:
    title_len = len(title.strip())
    highlight_len = len(highlights.strip())
    why_len = len(why_selected.strip())
    title_score = min(title_len / 60.0, 1.0) * 0.30
    highlight_score = min(highlight_len / 260.0, 1.0) * 0.45
    why_score = min(why_len / 180.0, 1.0) * 0.25
    # Penalize blank metadata to avoid saturation on templated outputs.
    if highlight_len == 0:
        highlight_score = 0.0
    if why_len == 0:
        why_score = 0.0
    return _clamp01(title_score + highlight_score + why_score)


def judge_search(
    *,
    items: list[dict[str, Any]],
    expected: dict[str, Any],
    rubric: dict[str, Any],
    query: str = "",
) -> JudgeResult:
    min_results = int(expected.get("min_results", 1))
    target_results = int(expected.get("target_results", min_results))
    if target_results < min_results:
        target_results = min_results
    required_domains = [str(domain).lower() for domain in expected.get("required_domains") or []]
    result_count = len(items)
    count_score = _clamp01(result_count / max(target_results, 1))

    query_terms = _tokenize_query(query or str(expected.get("query") or ""))
    domain_scores: dict[str, float] = {}
    relevance_values: list[float] = []
    freshness_values: list[float] = []
    content_values: list[float] = []

    distinct_domains = {
        (item.get("domain") or urlparse(str(item.get("url") or "")).netloc or "").lower()
        for item in items
    }
    distinct_domains = {domain for domain in distinct_domains if domain}
    coverage_score = _clamp01(len(distinct_domains) / max(min(result_count, 6), 1))

    for item in items:
        domain = (item.get("domain") or urlparse(str(item.get("url") or "")).netloc or "").lower()
        domain_scores[domain] = max(domain_scores.get(domain, 0.0), _score_domain_authority(domain))
        title = str(item.get("title") or "")
        highlights_raw = item.get("highlights") or []
        if isinstance(highlights_raw, list):
            highlights = " ".join(str(part) for part in highlights_raw if part)
        else:
            highlights = str(highlights_raw)
        why_selected = str(item.get("why_selected") or "")
        text_blob = " ".join([title, highlights, why_selected])
        relevance_values.append(_score_relevance_item(query_terms, text_blob))
        freshness_values.append(_score_freshness_item(item, text_blob))
        content_values.append(_score_content_quality_item(title, highlights, why_selected))

    authority_score = _clamp01(_average(list(domain_scores.values())) if domain_scores else 0.0)
    freshness_score = _clamp01(_average(freshness_values))
    relevance_score = _clamp01(_average(relevance_values))
    content_quality = _clamp01(_average(content_values))

    domain_hit = 0.5
    if required_domains:
        hit_count = sum(
            1
            for required in required_domains
            if any(required in domain for domain in distinct_domains)
        )
        domain_hit = _clamp01(hit_count / len(required_domains))

    weight_map = {
        "result_count": 0.10,
        "relevance": 0.25,
        "authority": 0.20,
        "coverage": 0.15,
        "freshness": 0.10,
        "content_quality": 0.15,
        "required_domain_hit": 0.05,
    }
    subscores = {
        "result_count": count_score,
        "relevance": relevance_score,
        "authority": authority_score,
        "coverage": coverage_score,
        "freshness": freshness_score,
        "content_quality": content_quality,
        "required_domain_hit": domain_hit,
    }
    score = _clamp01(sum(subscores[key] * weight_map[key] for key in subscores))
    pass_threshold = float(expected.get("pass_threshold", 0.6))
    passed = result_count >= min_results and score >= pass_threshold and domain_hit >= 0.5
    reason = (
        f"搜索评分={score:.3f}（relevance={relevance_score:.3f}, authority={authority_score:.3f}, coverage={coverage_score:.3f}）"
        if passed
        else f"搜索质量未达标（relevance={relevance_score:.3f}, authority={authority_score:.3f}, count={count_score:.3f}）"
    )
    if rubric.get("strict"):
        passed = passed and score >= 0.7
    return JudgeResult(
        score=score,
        subscores=subscores,
        passed=passed,
        reason=reason,
        details={
            "query_terms": query_terms,
            "query_terms_count": len(query_terms),
            "authority_domain_scores": dict(sorted(domain_scores.items(), key=lambda item: item[1], reverse=True)[:8]),
            "relevance_min": round(min(relevance_values), 4) if relevance_values else 0.0,
            "relevance_max": round(max(relevance_values), 4) if relevance_values else 0.0,
            "relevance_avg": round(_average(relevance_values), 4) if relevance_values else 0.0,
            "target_results": target_results,
        },
    )


def judge_ingest(
    *,
    clean_markdown: str,
    chunk_count: int,
    parse_error_tag: str | None = None,
    expected: dict[str, Any],
    rubric: dict[str, Any],
) -> JudgeResult:
    expect_failure = bool(expected.get("expect_failure", False))
    if expect_failure:
        allowed_error_tags = {
            str(tag).strip()
            for tag in (expected.get("error_tags") or [])
            if str(tag).strip()
        }
        has_error = bool(parse_error_tag)
        error_match = has_error and (not allowed_error_tags or parse_error_tag in allowed_error_tags)
        subscores = {
            "failure_detected": 1.0 if has_error else 0.0,
            "error_tag_match": 1.0 if error_match else 0.0,
            "unexpected_markdown_output": 1.0 if not (clean_markdown or "").strip() else 0.0,
        }
        score = _clamp01(_average(list(subscores.values())))
        passed = bool(error_match)
        reason = (
            f"失败路径符合预期（error_tag={parse_error_tag or 'none'}）"
            if passed
            else f"失败路径未命中预期（error_tag={parse_error_tag or 'none'}）"
        )
        return JudgeResult(
            score=score,
            subscores=subscores,
            passed=passed,
            reason=reason,
            details={"expected_error_tags": sorted(allowed_error_tags)},
        )

    min_chunks = int(expected.get("min_chunks", 1))
    min_chars = int(expected.get("min_chars", 80))
    content = (clean_markdown or "").strip()
    length = len(content)

    chunk_score = _clamp01(chunk_count / max(min_chunks, 1))
    length_score = _clamp01(length / max(min_chars, 1))
    heading_score = _clamp01(1.0 if re.search(r"^#{1,4}\s+\S+", content, flags=re.MULTILINE) else 0.0)
    context_score = _clamp01(1.0 if chunk_count > 0 and length > 0 else 0.0)

    subscores = {
        "chunk_count": chunk_score,
        "markdown_length": length_score,
        "heading_fidelity": heading_score,
        "chunk_context_integrity": context_score,
    }
    score = _clamp01(_average(list(subscores.values())))
    pass_threshold = float(expected.get("pass_threshold", 0.6))
    passed = chunk_count >= min_chunks and score >= pass_threshold
    if rubric.get("require_heading", False):
        passed = passed and heading_score >= 1.0
    reason = "解析与规范化结果达标" if passed else "解析结果不足，需排查解析链路"
    return JudgeResult(score=score, subscores=subscores, passed=passed, reason=reason, details={})


def judge_summary(
    *,
    summary_text: str,
    source_text: str,
    expected: dict[str, Any],
    rubric: dict[str, Any],
) -> JudgeResult:
    summary = (summary_text or "").strip()
    source = (source_text or "").strip()
    summary_len = len(summary)
    source_len = len(source)
    min_chars = int(expected.get("min_chars", 80))
    target_chars = int(expected.get("target_chars", max(min_chars, int(min_chars * 1.4))))
    max_ratio = float(expected.get("max_ratio", 0.5))
    min_ratio = float(expected.get("min_ratio", 0.08))
    must_include = [str(keyword).strip().lower() for keyword in expected.get("must_include") or [] if str(keyword).strip()]
    raw_groups = expected.get("must_include_groups") or []
    must_include_groups: list[list[str]] = []
    if isinstance(raw_groups, list):
        for group in raw_groups:
            if isinstance(group, str):
                parts = [part.strip().lower() for part in re.split(r"[|/]", group) if part and part.strip()]
            elif isinstance(group, (list, tuple, set)):
                parts = [str(part).strip().lower() for part in group if str(part).strip()]
            else:
                parts = []
            if parts:
                must_include_groups.append(parts)
    if not must_include_groups and must_include:
        must_include_groups = [[keyword] for keyword in must_include]
    ratio = summary_len / max(source_len, 1)

    if summary_len < min_chars:
        length_score = _clamp01(summary_len / max(min_chars, 1))
    else:
        deviation = abs(summary_len - target_chars) / max(target_chars, 1)
        length_score = _clamp01(1.0 - min(deviation, 1.0) * 0.6)

    if ratio < min_ratio:
        compression_score = _clamp01(ratio / max(min_ratio, 0.01))
    elif ratio <= max_ratio:
        in_band = (ratio - min_ratio) / max(max_ratio - min_ratio, 0.01)
        compression_score = _clamp01(1.0 - in_band * 0.15)
    else:
        compression_score = _clamp01(1.0 - (ratio - max_ratio) * 2.5)
    if not must_include_groups:
        coverage_score = 1.0
        matched_groups = 0
    else:
        summary_lower = summary.lower()
        matched_groups = sum(
            1
            for group in must_include_groups
            if any(keyword in summary_lower for keyword in group)
        )
        coverage_score = _clamp01(matched_groups / len(must_include_groups))
    summary_terms = _tokenize_query(summary)
    source_terms = set(_tokenize_query(source))
    term_overlap = (
        sum(1.0 for term in summary_terms if term in source_terms) / len(summary_terms)
        if summary_terms and source_terms
        else 0.0
    )
    supported_claim_ratio = _clamp01(coverage_score * 0.6 + term_overlap * 0.4)
    hallucination_proxy = _clamp01(0.2 + term_overlap * 0.8 if summary_terms else 0.0)

    subscores = {
        "key_point_coverage": coverage_score,
        "supported_claim_ratio": supported_claim_ratio,
        "compression_loss_control": compression_score,
        "hallucination_control": hallucination_proxy,
        "length": length_score,
    }
    score = _clamp01(_average(list(subscores.values())))
    pass_threshold = float(expected.get("pass_threshold", 0.62))
    passed = summary_len >= min_chars and score >= pass_threshold
    if rubric.get("strict"):
        passed = passed and coverage_score >= 0.6 and supported_claim_ratio >= 0.55
    reason = "摘要质量达标" if passed else "摘要质量未达标"
    return JudgeResult(
        score=score,
        subscores=subscores,
        passed=passed,
        reason=reason,
        details={
            "summary_length": summary_len,
            "source_length": source_len,
            "compression_ratio": round(ratio, 4),
            "target_chars": target_chars,
            "term_overlap": round(term_overlap, 4),
            "must_include_count": len(must_include),
            "must_include_groups_count": len(must_include_groups),
            "must_include_groups_matched": matched_groups,
        },
    )


def judge_chat(
    *,
    question: str,
    answer: str,
    evidence_count: int,
    route: str,
    web_searched: bool,
    expected: dict[str, Any],
    rubric: dict[str, Any],
) -> JudgeResult:
    text = (answer or "").strip()
    min_chars = int(expected.get("min_chars", 80))
    min_citations = int(expected.get("min_citations", 1))
    should_use_web = bool(expected.get("should_use_web", False))
    expected_route_raw = expected.get("expected_route", expected.get("expected_routes"))
    expected_routes: list[str] = []
    if isinstance(expected_route_raw, str):
        expected_routes = [expected_route_raw.strip()]
    elif isinstance(expected_route_raw, (list, tuple, set)):
        expected_routes = [str(item).strip() for item in expected_route_raw if str(item).strip()]
    expected_keywords = [
        str(item).strip().lower()
        for item in (expected.get("expected_keywords") or [])
        if str(item).strip()
    ]

    length_score = _clamp01(len(text) / max(min_chars, 1))
    relevance_score = _score_relevance_item(
        _tokenize_query(question),
        text,
    )
    if expected_keywords:
        blob = text.lower()
        keyword_hit = sum(1 for keyword in expected_keywords if keyword in blob)
        keyword_coverage = keyword_hit / len(expected_keywords)
        relevance_score = _clamp01(relevance_score * 0.7 + keyword_coverage * 0.3)

    if min_citations <= 0:
        groundedness = 1.0 if text else 0.0
        citation_validity = 1.0
    else:
        groundedness = _clamp01(evidence_count / max(min_citations, 1))
        citation_validity = _clamp01(1.0 if evidence_count >= min_citations else 0.0)

    if should_use_web:
        web_judgement = _clamp01(1.0 if web_searched else 0.2)
    else:
        web_judgement = _clamp01(1.0 if not web_searched else 0.55)

    known_routes = {"article_qa", "notebook_search", "recommendation", "general"}
    if expected_routes:
        route_reasonable = _clamp01(
            0.92 if route in expected_routes else (0.4 if route in known_routes else 0.12)
        )
    else:
        route_reasonable = _clamp01(0.9 if route in known_routes else 0.12)

    fallback_penalty = 0.35 if ("抱歉" in text and ("无法回答" in text or "重试" in text or "超时" in text)) else 0.0

    subscores = {
        "accuracy_proxy": _clamp01(max(length_score - fallback_penalty, 0.0)),
        "relevance": relevance_score,
        "groundedness": groundedness,
        "citation_validity": citation_validity,
        "web_decision": web_judgement,
        "route_reasonableness": route_reasonable,
    }
    score = _clamp01(_average(list(subscores.values())))
    pass_threshold = float(expected.get("pass_threshold", 0.6))
    passed = len(text) >= min_chars and score >= pass_threshold
    if rubric.get("require_citation", False):
        passed = passed and citation_validity >= 1.0
    if rubric.get("require_web", False):
        passed = passed and should_use_web and web_searched
    reason = "回答质量达标" if passed else "回答质量未达标"
    return JudgeResult(
        score=score,
        subscores=subscores,
        passed=passed,
        reason=reason,
        details={
            "expected_routes": expected_routes,
            "expected_keywords_count": len(expected_keywords),
        },
    )
