"""Stage A – Task Parsing.

Converts a raw user query + notebook context into a structured TaskSpec.
First version is rule-based (keyword matching + heuristics).
A future iteration can delegate to an LLM for deeper understanding.
"""

from __future__ import annotations

import re

from app.modules.search.pipeline.types import (
    CoverageFacet,
    NotebookContext,
    SearchIntent,
    SourceMix,
    TaskSpec,
    TimeSensitivity,
)

# ── keyword banks ──────────────────────────────────────────────────────────

_COMPARE_KEYWORDS = re.compile(
    r"\b(compare|vs\.?|versus|difference|对比|比较|区别)\b", re.IGNORECASE
)
_ANSWER_KEYWORDS = re.compile(
    r"\b(what is|how to|why does|explain|是什么|怎么|为什么|如何)\b", re.IGNORECASE
)
_LIT_REVIEW_KEYWORDS = re.compile(
    r"\b(survey|review|综述|研究|research|literature|研究进展|overview)\b",
    re.IGNORECASE,
)
_PRIMARY_SOURCE_KEYWORDS = re.compile(
    r"\b(paper|论文|arxiv|rfc|specification|spec|标准|报告|report|benchmark)\b",
    re.IGNORECASE,
)
_RECENCY_KEYWORDS = re.compile(
    r"\b(latest|newest|recent|2025|2026|最新|近期|今年)\b", re.IGNORECASE
)

_ACADEMIC_DOMAIN_KEYWORDS = re.compile(
    r"\b(arxiv|pubmed|journal|doi|论文|学术|academic|研究)\b", re.IGNORECASE
)
_TECH_DOMAIN_KEYWORDS = re.compile(
    r"\b(api|sdk|framework|library|deploy|architecture|kubernetes|docker|"
    r"react|python|rust|golang|typescript|数据库|微服务|云原生)\b",
    re.IGNORECASE,
)
_BIOMED_DOMAIN_KEYWORDS = re.compile(
    r"\b(clinical|patient|drug|therapy|gene|protein|医学|临床|药物|基因)\b",
    re.IGNORECASE,
)
_POLICY_DOMAIN_KEYWORDS = re.compile(
    r"\b(policy|regulation|law|government|政策|法规|监管|合规)\b", re.IGNORECASE
)


def parse_task(
    query: str,
    notebook: NotebookContext,
) -> TaskSpec:
    """Analyse *query* and *notebook* context to produce a ``TaskSpec``."""

    intent = _detect_intent(query)
    domain = _detect_domain(query)
    time_sensitivity = _detect_time_sensitivity(query)
    primary_pref = _detect_primary_preference(query, intent)
    coverage = _detect_coverage_facets(query, intent, notebook)
    source_mix = _detect_source_mix(domain, intent)
    novelty_req = _detect_novelty_requirement(notebook)

    return TaskSpec(
        intent=intent,
        domain=domain,
        time_sensitivity=time_sensitivity,
        expected_source_mix=source_mix,
        coverage_facets=coverage,
        primary_source_preference=primary_pref,
        notebook_novelty_requirement=novelty_req,
    )


# ── intent detection ───────────────────────────────────────────────────────

def _detect_intent(query: str) -> SearchIntent:
    if _COMPARE_KEYWORDS.search(query):
        return SearchIntent.COMPARE
    if _PRIMARY_SOURCE_KEYWORDS.search(query):
        return SearchIntent.FIND_PRIMARY_SOURCE
    if _LIT_REVIEW_KEYWORDS.search(query):
        return SearchIntent.LITERATURE_REVIEW
    if _ANSWER_KEYWORDS.search(query):
        return SearchIntent.ANSWER
    return SearchIntent.EXPLORE


# ── domain detection ───────────────────────────────────────────────────────

def _detect_domain(query: str) -> str:
    if _BIOMED_DOMAIN_KEYWORDS.search(query):
        return "biomed"
    if _POLICY_DOMAIN_KEYWORDS.search(query):
        return "policy"
    if _ACADEMIC_DOMAIN_KEYWORDS.search(query):
        return "cs"
    if _TECH_DOMAIN_KEYWORDS.search(query):
        return "cs"
    return "general"


# ── time sensitivity ───────────────────────────────────────────────────────

def _detect_time_sensitivity(query: str) -> TimeSensitivity:
    if _RECENCY_KEYWORDS.search(query):
        return TimeSensitivity.HIGH
    return TimeSensitivity.MEDIUM


# ── primary-source preference ──────────────────────────────────────────────

def _detect_primary_preference(
    query: str,
    intent: SearchIntent,
) -> TimeSensitivity:
    if intent in (SearchIntent.FIND_PRIMARY_SOURCE, SearchIntent.LITERATURE_REVIEW):
        return TimeSensitivity.HIGH
    if _PRIMARY_SOURCE_KEYWORDS.search(query):
        return TimeSensitivity.HIGH
    return TimeSensitivity.MEDIUM


# ── coverage facets ────────────────────────────────────────────────────────

def _detect_coverage_facets(
    query: str,
    intent: SearchIntent,
    notebook: NotebookContext,
) -> list[CoverageFacet]:
    facets: list[CoverageFacet] = [CoverageFacet.OVERVIEW]

    if _RECENCY_KEYWORDS.search(query):
        facets.append(CoverageFacet.RECENT)

    if intent in (SearchIntent.FIND_PRIMARY_SOURCE, SearchIntent.LITERATURE_REVIEW):
        facets.append(CoverageFacet.PRIMARY)

    if intent == SearchIntent.COMPARE or re.search(
        r"\b(risk|limitation|challenge|局限|风险|挑战|缺点)\b", query, re.IGNORECASE
    ):
        facets.append(CoverageFacet.CRITIQUE)

    if re.search(
        r"\b(implementation|deploy|case study|实现|部署|案例|architecture|架构)\b",
        query,
        re.IGNORECASE,
    ):
        facets.append(CoverageFacet.IMPLEMENTATION)

    # If the notebook already has a lot of overview content, push toward
    # primary / critique / implementation to fill coverage gaps.
    if len(notebook.existing_article_titles) >= 5:
        for gap in (CoverageFacet.PRIMARY, CoverageFacet.CRITIQUE, CoverageFacet.IMPLEMENTATION):
            if gap not in facets:
                facets.append(gap)

    return list(dict.fromkeys(facets))  # dedupe, preserve order


# ── source mix ─────────────────────────────────────────────────────────────

def _detect_source_mix(domain: str, intent: SearchIntent) -> list[SourceMix]:
    mix: list[SourceMix] = [SourceMix.WEB]
    if domain in ("cs", "biomed") or intent in (
        SearchIntent.FIND_PRIMARY_SOURCE,
        SearchIntent.LITERATURE_REVIEW,
    ):
        mix.append(SourceMix.PAPER)
    if intent == SearchIntent.FIND_PRIMARY_SOURCE:
        mix.append(SourceMix.OFFICIAL_DOC)
    return mix


# ── novelty requirement ────────────────────────────────────────────────────

def _detect_novelty_requirement(notebook: NotebookContext) -> TimeSensitivity:
    if len(notebook.existing_article_urls) >= 10:
        return TimeSensitivity.HIGH
    if len(notebook.existing_article_urls) >= 3:
        return TimeSensitivity.MEDIUM
    return TimeSensitivity.LOW
