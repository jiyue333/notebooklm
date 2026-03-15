"""Stage D – Candidate Generation + Judge.

Generates 1-3 summary candidates using different prompt styles,
then scores each with a judge rubric to pick the best one.

The first version uses a single LLM call per candidate via the
project's ``build_user_chat_model`` infrastructure.  The judge
is rule-based (heuristic) to avoid an extra LLM round-trip;
a future version can use a second LLM pass.
"""

from __future__ import annotations

import re

import structlog

from app.modules.ai.summary.pipeline.types import (
    CandidateStyle,
    EvidenceBullet,
    JudgeScoreBreakdown,
    ScoredSummaryCandidate,
    SummaryCandidate,
    SummaryRoute,
)

logger = structlog.get_logger(__name__)


async def generate_candidates(
    title: str,
    article_type: str,
    route: SummaryRoute,
    evidence: list[EvidenceBullet],
    clean_markdown: str,
    *,
    language: str = "auto",
) -> list[ScoredSummaryCandidate]:
    """Generate and judge summary candidates.

    For Route X (conservative), a single safe candidate is produced
    from a truncated content window.  For other routes, up to 3
    style variants are generated from the evidence bullets.
    """

    del language

    if route == SummaryRoute.X:
        candidates = [_conservative_candidate(title, clean_markdown)]
    elif route == SummaryRoute.S:
        candidates = _build_route_s_candidates(title, evidence)
    elif route == SummaryRoute.M:
        candidates = _build_route_m_candidates(title, article_type, evidence)
    else:
        candidates = _build_route_l_candidates(title, article_type, evidence)

    scored = [_judge(c, evidence) for c in candidates]
    scored.sort(key=lambda s: s.scores.total, reverse=True)
    for i, s in enumerate(scored):
        s.rank = i + 1
    return scored


# ── candidate construction ─────────────────────────────────────────────────

def _build_route_s_candidates(
    title: str,
    evidence: list[EvidenceBullet],
) -> list[SummaryCandidate]:
    prioritized = _prioritize_indexes(
        evidence,
        emphasis=["result", "implication", "method", "problem"],
        limit=5,
    )
    if not prioritized:
        return []
    return [
        _candidate_from_indexes(title, evidence, prioritized, CandidateStyle.CLAIM_FIRST, route="S"),
        _candidate_from_indexes(
            title,
            evidence,
            _prioritize_indexes(evidence, emphasis=["method", "result", "implication"], limit=5),
            CandidateStyle.CONTRIBUTION_FIRST,
            route="S",
        ),
        _candidate_from_indexes(
            title,
            evidence,
            _prioritize_indexes(evidence, emphasis=["problem", "background", "result"], limit=5),
            CandidateStyle.READER_FIRST,
            route="S",
        ),
    ]


def _build_route_m_candidates(
    title: str,
    article_type: str,
    evidence: list[EvidenceBullet],
) -> list[SummaryCandidate]:
    grouped = _group_indexes_by_role(evidence)
    if not grouped:
        return []
    micro_indexes = _build_micro_summary_indexes(grouped)
    if not micro_indexes:
        return []
    variants = [
        (CandidateStyle.CLAIM_FIRST, micro_indexes),
        (CandidateStyle.CONTRIBUTION_FIRST, _reorder_indexes(micro_indexes, evidence, ["method", "how_to", "result"])),
        (CandidateStyle.READER_FIRST, _reorder_indexes(micro_indexes, evidence, ["problem", "background", "result"])),
    ]
    return [
        _candidate_from_indexes(
            title,
            evidence,
            indexes,
            style,
            route="M",
            intro=f"这篇{_article_label(article_type)}的核心信息可以概括为：",
        )
        for style, indexes in variants
        if indexes
    ]


def _build_route_l_candidates(
    title: str,
    article_type: str,
    evidence: list[EvidenceBullet],
) -> list[SummaryCandidate]:
    grouped = _group_indexes_by_role(evidence)
    if not grouped:
        return []

    hierarchical = _build_hierarchical_indexes(grouped)
    if not hierarchical:
        return []
    variants = [
        (CandidateStyle.CLAIM_FIRST, hierarchical),
        (CandidateStyle.CONTRIBUTION_FIRST, _reorder_indexes(hierarchical, evidence, ["method", "result", "implication"])),
        (CandidateStyle.READER_FIRST, _reorder_indexes(hierarchical, evidence, ["problem", "background", "result"])),
    ]
    return [
        _candidate_from_indexes(
            title,
            evidence,
            indexes,
            style,
            route="L",
            intro=f"围绕这篇{_article_label(article_type)}，先看核心结论，再看支撑证据与适用边界：",
        )
        for style, indexes in variants
        if indexes
    ]


def _conservative_candidate(title: str, markdown: str) -> SummaryCandidate:
    """Route X fallback: extract from first 2000 chars only."""
    truncated = _extract_conservative_window(markdown)
    sentences = re.split(r"(?<=[.!?])\s+", truncated[:2500])
    key_sentences = [s.strip() for s in sentences if len(s.strip()) > 30][:5]
    text = f"{title}. " + " ".join(key_sentences) if key_sentences else title
    return SummaryCandidate(
        style=CandidateStyle.CLAIM_FIRST,
        text=text,
        metadata={"conservative": True, "route": "X"},
    )


def _compose(title: str, bullet_texts: list[str]) -> str:
    """Stitch evidence bullets into a paragraph."""
    if not bullet_texts:
        return title
    joined = " ".join(bullet_texts)
    if not joined.endswith("."):
        joined += "."
    return joined


def _candidate_from_indexes(
    title: str,
    evidence: list[EvidenceBullet],
    indexes: list[int],
    style: CandidateStyle,
    *,
    route: str,
    intro: str | None = None,
) -> SummaryCandidate:
    selected = [evidence[index].text for index in indexes if 0 <= index < len(evidence)]
    if not selected:
        return SummaryCandidate(style=style, text=title, metadata={"route": route})
    body = _compose(title, selected)
    if intro:
        body = f"{intro} {body}"
    return SummaryCandidate(
        style=style,
        text=body,
        evidence_bullet_ids=indexes,
        metadata={"route": route},
    )


def _group_indexes_by_role(evidence: list[EvidenceBullet]) -> dict[str, list[int]]:
    grouped: dict[str, list[int]] = {}
    for index, bullet in enumerate(evidence):
        grouped.setdefault(bullet.role.value, []).append(index)
    return grouped


def _build_micro_summary_indexes(grouped: dict[str, list[int]]) -> list[int]:
    quotas = {
        "problem": 1,
        "background": 1,
        "method": 2,
        "how_to": 2,
        "result": 2,
        "implication": 1,
        "limitation": 1,
    }
    indexes: list[int] = []
    for role, limit in quotas.items():
        indexes.extend(grouped.get(role, [])[:limit])
    return list(dict.fromkeys(indexes))[:6]


def _build_hierarchical_indexes(grouped: dict[str, list[int]]) -> list[int]:
    clusters = [
        grouped.get("problem", [])[:1] + grouped.get("background", [])[:1],
        grouped.get("method", [])[:2] + grouped.get("how_to", [])[:1],
        grouped.get("result", [])[:2] + grouped.get("implication", [])[:1],
        grouped.get("limitation", [])[:1],
    ]
    indexes: list[int] = []
    for cluster in clusters:
        indexes.extend(cluster[:2])
    return list(dict.fromkeys(indexes))[:7]


def _prioritize_indexes(
    evidence: list[EvidenceBullet],
    *,
    emphasis: list[str],
    limit: int,
) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()
    for role in emphasis:
        for index, bullet in enumerate(evidence):
            if bullet.role.value != role or index in seen:
                continue
            indexes.append(index)
            seen.add(index)
            if len(indexes) >= limit:
                return indexes
    for index, _bullet in enumerate(evidence):
        if index in seen:
            continue
        indexes.append(index)
        if len(indexes) >= limit:
            break
    return indexes


def _reorder_indexes(
    indexes: list[int],
    evidence: list[EvidenceBullet],
    emphasis: list[str],
) -> list[int]:
    emphasized: list[int] = []
    remainder: list[int] = []
    emphasis_set = set(emphasis)
    for index in indexes:
        if evidence[index].role.value in emphasis_set:
            emphasized.append(index)
        else:
            remainder.append(index)
    ordered = emphasized + remainder
    return list(dict.fromkeys(ordered))


def _extract_conservative_window(markdown: str) -> str:
    if not markdown.strip():
        return ""

    safe_sections: list[str] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("#"):
            if current_lines and _is_safe_heading(current_heading):
                safe_sections.append("\n".join(current_lines))
            current_heading = line.lstrip("#").strip().lower()
            current_lines = [line]
        elif line.strip():
            current_lines.append(line)
    if current_lines and _is_safe_heading(current_heading):
        safe_sections.append("\n".join(current_lines))

    if safe_sections:
        return "\n\n".join(safe_sections)
    return markdown[:2000]


def _is_safe_heading(heading: str) -> bool:
    if not heading:
        return True
    return any(keyword in heading for keyword in (
        "abstract",
        "introduction",
        "overview",
        "conclusion",
        "discussion",
        "implication",
        "caption",
    ))


def _article_label(article_type: str) -> str:
    labels = {
        "paper": "文章",
        "report": "报告",
        "tutorial": "教程",
        "news": "报道",
        "docs": "文档",
    }
    return labels.get(article_type, "内容")


# ── heuristic judge ────────────────────────────────────────────────────────

def _judge(
    candidate: SummaryCandidate,
    evidence: list[EvidenceBullet],
) -> ScoredSummaryCandidate:
    text = candidate.text
    fidelity = _score_fidelity(text, evidence)
    coverage = _score_coverage(text, evidence)
    clarity = _score_clarity(text)
    concision = _score_concision(text)

    total = round(
        0.40 * fidelity
        + 0.30 * coverage
        + 0.20 * clarity
        + 0.10 * concision,
        4,
    )

    return ScoredSummaryCandidate(
        candidate=candidate,
        scores=JudgeScoreBreakdown(
            fidelity=round(fidelity, 4),
            coverage=round(coverage, 4),
            clarity=round(clarity, 4),
            concision=round(concision, 4),
            total=total,
        ),
    )


def _score_fidelity(text: str, evidence: list[EvidenceBullet]) -> float:
    """How many evidence bullets have at least partial overlap in the summary."""
    if not evidence:
        return 0.5
    matched = sum(
        1 for b in evidence
        if any(word in text.lower() for word in b.text.lower().split()[:5] if len(word) > 4)
    )
    return min(matched / max(len(evidence), 1), 1.0)


def _score_coverage(text: str, evidence: list[EvidenceBullet]) -> float:
    """Fraction of distinct section roles represented in the summary."""
    roles_in_evidence = {b.role for b in evidence}
    if not roles_in_evidence:
        return 0.5
    roles_mentioned = set()
    for b in evidence:
        key_words = [w for w in b.text.lower().split() if len(w) > 5][:3]
        if any(w in text.lower() for w in key_words):
            roles_mentioned.add(b.role)
    return len(roles_mentioned) / len(roles_in_evidence)


def _score_clarity(text: str) -> float:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if not sentences:
        return 0.3
    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    if 10 <= avg_len <= 30:
        return 0.9
    if avg_len < 10:
        return 0.5
    return 0.6


def _score_concision(text: str) -> float:
    word_count = len(text.split())
    if 40 <= word_count <= 150:
        return 1.0
    if word_count < 40:
        return 0.6
    if word_count <= 250:
        return 0.7
    return 0.4
