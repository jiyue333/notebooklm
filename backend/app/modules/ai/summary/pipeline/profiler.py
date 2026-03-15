"""Stage A – Article Profiling.

Analyses the article's content to classify its type, evidence style,
structure quality, and section roles.  This profile drives downstream
routing and prompt selection.

First version is rule-based; a future iteration can use a small LLM.
"""

from __future__ import annotations

import re

from app.modules.ai.summary.pipeline.types import (
    ArticleProfile,
    ArticleType,
    EvidenceStyle,
    SectionRole,
    StructureQuality,
    SummaryInput,
)


def profile_article(inp: SummaryInput) -> ArticleProfile:
    md = inp.clean_markdown
    title = inp.title.lower()

    return ArticleProfile(
        article_type=_detect_type(md, title),
        evidence_style=_detect_evidence_style(md),
        structure_quality=_detect_structure_quality(md, inp.quality_score),
        domain=_detect_domain(md, title),
        section_roles=_detect_section_roles(md),
        important_entities=_extract_entities(md),
        word_count=len(md.split()),
    )


# ── type detection ─────────────────────────────────────────────────────────

_PAPER_HINTS = re.compile(
    r"\b(abstract|references|citation|doi|arxiv|methodology|experiment|hypothesis)\b",
    re.IGNORECASE,
)
_TUTORIAL_HINTS = re.compile(
    r"\b(step \d|how to|tutorial|getting started|installation|setup|example)\b",
    re.IGNORECASE,
)
_NEWS_HINTS = re.compile(
    r"\b(reported|according to|announced|press release|breaking)\b",
    re.IGNORECASE,
)
_DOCS_HINTS = re.compile(
    r"\b(api reference|parameters|returns|usage|configuration|endpoint)\b",
    re.IGNORECASE,
)


def _detect_type(md: str, title: str) -> ArticleType:
    sample = md[:3000]
    if _PAPER_HINTS.search(sample):
        return ArticleType.PAPER
    if _DOCS_HINTS.search(sample):
        return ArticleType.DOCS
    if _TUTORIAL_HINTS.search(sample):
        return ArticleType.TUTORIAL
    if _NEWS_HINTS.search(sample):
        return ArticleType.NEWS
    if re.search(r"\b(report|whitepaper|policy|executive summary)\b", sample, re.IGNORECASE):
        return ArticleType.REPORT
    return ArticleType.BLOG


# ── evidence style ─────────────────────────────────────────────────────────

def _detect_evidence_style(md: str) -> EvidenceStyle:
    sample = md[:5000]
    quant = len(re.findall(r"\d+\.?\d*\s*%|p\s*[<>=]|table\s+\d|figure\s+\d", sample, re.IGNORECASE))
    qual = len(re.findall(r"\b(interview|case study|observation|qualitative)\b", sample, re.IGNORECASE))
    if quant >= 3 and qual >= 2:
        return EvidenceStyle.MIXED
    if quant >= 3:
        return EvidenceStyle.QUANTITATIVE
    if qual >= 2:
        return EvidenceStyle.QUALITATIVE
    return EvidenceStyle.MIXED


# ── structure quality ──────────────────────────────────────────────────────

def _detect_structure_quality(md: str, quality_score: float) -> StructureQuality:
    if quality_score >= 0.7:
        return StructureQuality.HIGH
    if quality_score >= 0.4:
        return StructureQuality.MEDIUM
    headings = sum(1 for l in md.splitlines() if l.startswith("#"))
    if headings >= 4:
        return StructureQuality.MEDIUM
    return StructureQuality.LOW


# ── domain ─────────────────────────────────────────────────────────────────

def _detect_domain(md: str, title: str) -> str:
    combined = f"{title} {md[:2000]}".lower()
    if re.search(r"\b(clinical|patient|drug|gene|biomedical)\b", combined):
        return "biomed"
    if re.search(r"\b(api|framework|deploy|kubernetes|algorithm|neural)\b", combined):
        return "cs"
    if re.search(r"\b(policy|regulation|government|legislation)\b", combined):
        return "policy"
    return "general"


# ── section roles ──────────────────────────────────────────────────────────

_ROLE_PATTERNS: list[tuple[re.Pattern, SectionRole]] = [
    (re.compile(r"background|introduction|overview|context", re.I), SectionRole.BACKGROUND),
    (re.compile(r"problem|motivation|challenge|research question", re.I), SectionRole.PROBLEM),
    (re.compile(r"method|approach|design|implementation|architecture", re.I), SectionRole.METHOD),
    (re.compile(r"result|finding|evaluation|experiment|performance", re.I), SectionRole.RESULT),
    (re.compile(r"limitation|threat|future work|weakness", re.I), SectionRole.LIMITATION),
    (re.compile(r"conclusion|implication|discussion|significance", re.I), SectionRole.IMPLICATION),
    (re.compile(r"step|tutorial|how.to|guide|instruction", re.I), SectionRole.HOW_TO),
    (re.compile(r"opinion|commentary|editorial|perspective", re.I), SectionRole.OPINION),
]


def _detect_section_roles(md: str) -> dict[str, SectionRole]:
    roles: dict[str, SectionRole] = {}
    for line in md.splitlines():
        if not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip()
        if not heading:
            continue
        for pattern, role in _ROLE_PATTERNS:
            if pattern.search(heading):
                roles[heading] = role
                break
        if heading not in roles:
            roles[heading] = SectionRole.UNKNOWN
    return roles


# ── entity extraction (lightweight) ───────────────────────────────────────

def _extract_entities(md: str) -> list[str]:
    """Extract capitalised multi-word terms as proxy for important entities."""
    matches = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", md[:5000])
    seen: set[str] = set()
    entities: list[str] = []
    for m in matches:
        key = m.lower()
        if key not in seen and len(m) > 4:
            seen.add(key)
            entities.append(m)
        if len(entities) >= 15:
            break
    return entities
