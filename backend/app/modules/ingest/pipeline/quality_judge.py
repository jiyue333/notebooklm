"""Stage E – Parse Quality Judge.

Scores each ParseCandidate using the ADR-002 §4.6 formula:

    parse_score =
        0.20 * structure_integrity
      + 0.15 * reading_order
      + 0.15 * heading_quality
      + 0.10 * sentence_integrity
      + 0.10 * table_fidelity
      + 0.10 * reference_quality
      + 0.10 * metadata_consistency
      + 0.10 * anchorability
"""

from __future__ import annotations

import re

from app.modules.ingest.pipeline.types import (
    ParseCandidate,
    QualityScoreBreakdown,
    ScoredParseCandidate,
)

_LLM_FALLBACK_THRESHOLD = 0.35


def judge_candidates(
    candidates: list[ParseCandidate],
) -> list[ScoredParseCandidate]:
    """Score and rank all candidates. Best candidate gets rank=1."""

    scored = [_score_one(c) for c in candidates]
    scored.sort(key=lambda s: s.quality.total, reverse=True)
    for i, s in enumerate(scored):
        s.rank = i + 1
    return scored


def _score_one(c: ParseCandidate) -> ScoredParseCandidate:
    md = c.markdown
    q = QualityScoreBreakdown(
        structure_integrity=_structure_integrity(md),
        reading_order=_reading_order(md),
        heading_quality=_heading_quality(md),
        sentence_integrity=_sentence_integrity(md),
        table_fidelity=_table_fidelity(md),
        reference_quality=_reference_quality(md),
        metadata_consistency=_metadata_consistency(c),
        anchorability=_anchorability(md),
    )
    q.total = round(
        0.20 * q.structure_integrity
        + 0.15 * q.reading_order
        + 0.15 * q.heading_quality
        + 0.10 * q.sentence_integrity
        + 0.10 * q.table_fidelity
        + 0.10 * q.reference_quality
        + 0.10 * q.metadata_consistency
        + 0.10 * q.anchorability,
        4,
    )
    return ScoredParseCandidate(
        candidate=c,
        quality=q,
        needs_llm_fallback=q.total < _LLM_FALLBACK_THRESHOLD,
    )


# ── dimension scorers (0.0 – 1.0) ─────────────────────────────────────────

def _structure_integrity(md: str) -> float:
    """Are there markdown elements (headings, lists, code blocks)?"""
    lines = md.splitlines()
    if not lines:
        return 0.0
    structural = sum(
        1 for l in lines
        if l.startswith("#") or l.startswith("- ") or l.startswith("* ")
        or l.startswith("```") or l.startswith("|") or l.startswith("> ")
        or re.match(r"^\d+\.\s", l)
    )
    ratio = structural / len(lines)
    return _clamp(ratio * 4)  # 25% structural lines → 1.0


def _reading_order(md: str) -> float:
    """Check for obvious reading-order issues (e.g. heading after content)."""
    lines = md.splitlines()
    heading_positions = [i for i, l in enumerate(lines) if l.startswith("#")]
    if not heading_positions:
        return 0.4  # no headings at all → mediocre
    if heading_positions[0] > len(lines) * 0.3:
        return 0.3  # first heading very late → suspicious
    # headings should generally appear in increasing position
    monotonic = all(
        heading_positions[i] <= heading_positions[i + 1]
        for i in range(len(heading_positions) - 1)
    )
    return 1.0 if monotonic else 0.6


def _heading_quality(md: str) -> float:
    """Headings form a proper hierarchy (h1 → h2 → h3 etc.)."""
    levels: list[int] = []
    for line in md.splitlines():
        if line.startswith("#"):
            stripped = line.split(" ", 1)
            if stripped:
                levels.append(len(stripped[0]))
    if not levels:
        return 0.2
    if levels[0] > 2:
        return 0.3  # starts at h3+ → probably broken
    # check that levels never jump more than 1 step
    violations = sum(
        1 for i in range(1, len(levels))
        if levels[i] > levels[i - 1] + 1
    )
    return _clamp(1.0 - violations * 0.15)


def _sentence_integrity(md: str) -> float:
    """Check for broken sentences (very short lines mid-paragraph)."""
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    if len(lines) < 5:
        return 0.5
    short_lines = sum(
        1 for l in lines
        if len(l) < 20 and not l.startswith("#") and not l.startswith("-")
        and not l.startswith("|") and not l.startswith(">") and not l.startswith("```")
    )
    ratio = short_lines / len(lines)
    return _clamp(1.0 - ratio * 3)


def _table_fidelity(md: str) -> float:
    """If tables exist, are they well-formed (| separators)?"""
    table_lines = [l for l in md.splitlines() if l.strip().startswith("|")]
    if not table_lines:
        return 0.5  # no tables → neutral
    well_formed = sum(1 for l in table_lines if l.count("|") >= 2)
    return _clamp(well_formed / len(table_lines))


def _reference_quality(md: str) -> float:
    """Presence of reference/citation markers."""
    ref_patterns = re.findall(r"\[(\d+)\]|\[\^", md)
    links = re.findall(r"\[.+?\]\(.+?\)", md)
    if ref_patterns or len(links) >= 3:
        return 0.8
    if links:
        return 0.5
    return 0.2


def _metadata_consistency(c: ParseCandidate) -> float:
    """Does the candidate have reasonable metadata?"""
    score = 0.2
    if c.title and len(c.title) >= 5:
        score += 0.3
    if c.author:
        score += 0.2
    if c.published_at:
        score += 0.15
    if c.word_count >= 100:
        score += 0.15
    return _clamp(score)


def _anchorability(md: str) -> float:
    """Can we build jump anchors (headings, numbered sections)?"""
    headings = sum(1 for l in md.splitlines() if l.startswith("#"))
    if headings >= 5:
        return 1.0
    if headings >= 2:
        return 0.7
    if headings >= 1:
        return 0.4
    return 0.1


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
