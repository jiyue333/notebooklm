"""Stage B – Evidence Skeleton Extraction.

Extracts 8-12 key evidence bullets from the article, each tied to
section roles and assigned a salience score.  These bullets become
the factual backbone that the summary generator works from.

The first version uses heuristic extraction (heading-aware paragraph
ranking).  A future version can use an LLM for extraction.
"""

from __future__ import annotations

import re

from app.modules.ai.summary.pipeline.types import (
    ArticleProfile,
    ArticleType,
    EvidenceBullet,
    SectionRole,
    SummaryInput,
)

_TARGET_BULLETS = 10
_MIN_SENTENCE_LEN = 30

# Weight multiplier per section role (paper template).
_ROLE_WEIGHTS_PAPER: dict[SectionRole, float] = {
    SectionRole.RESULT: 1.5,
    SectionRole.METHOD: 1.2,
    SectionRole.LIMITATION: 1.1,
    SectionRole.IMPLICATION: 1.1,
    SectionRole.PROBLEM: 1.0,
    SectionRole.BACKGROUND: 0.6,
    SectionRole.HOW_TO: 0.8,
    SectionRole.OPINION: 0.7,
    SectionRole.UNKNOWN: 0.5,
}

_ROLE_WEIGHTS_DEFAULT: dict[SectionRole, float] = {
    SectionRole.RESULT: 1.3,
    SectionRole.METHOD: 1.0,
    SectionRole.IMPLICATION: 1.2,
    SectionRole.PROBLEM: 1.0,
    SectionRole.LIMITATION: 1.0,
    SectionRole.BACKGROUND: 0.7,
    SectionRole.HOW_TO: 1.1,
    SectionRole.OPINION: 0.8,
    SectionRole.UNKNOWN: 0.5,
}


def extract_evidence(
    inp: SummaryInput,
    profile: ArticleProfile,
) -> list[EvidenceBullet]:
    """Return up to ``_TARGET_BULLETS`` evidence bullets."""

    weights = (
        _ROLE_WEIGHTS_PAPER
        if profile.article_type == ArticleType.PAPER
        else _ROLE_WEIGHTS_DEFAULT
    )

    sections = _split_into_sections(inp, profile.section_roles)
    scored: list[tuple[str, SectionRole, float, list[str]]] = []

    for heading, role, paragraphs, block_ids in sections:
        weight = weights.get(role, 0.5)
        for para_index, para in enumerate(paragraphs):
            sentences = _split_sentences(para)
            for sent in sentences:
                if len(sent) < _MIN_SENTENCE_LEN:
                    continue
                score = weight * _sentence_salience(sent)
                block_id = block_ids[para_index] if para_index < len(block_ids) else None
                scored.append((sent, role, score, [block_id] if block_id else []))

    scored.sort(key=lambda x: x[2], reverse=True)
    top = scored[:_TARGET_BULLETS]

    return [
        EvidenceBullet(
            text=text.strip(),
            role=role,
            block_ids=block_ids,
            salience_score=round(score, 4),
        )
        for text, role, score, block_ids in top
    ]


# ── helpers ────────────────────────────────────────────────────────────────

def _split_into_sections(
    inp: SummaryInput,
    role_map: dict[str, SectionRole],
) -> list[tuple[str, SectionRole, list[str], list[str | None]]]:
    """Split markdown into (heading, role, paragraphs) tuples."""

    if inp.block_graph_json:
        sections = _split_from_block_graph(inp, role_map)
        if sections:
            return sections

    md = inp.clean_markdown
    sections: list[tuple[str, SectionRole, list[str], list[str | None]]] = []
    current_heading = ""
    current_role = SectionRole.UNKNOWN
    current_paras: list[str] = []
    current_block_ids: list[str | None] = []

    for line in md.splitlines():
        if line.startswith("#"):
            if current_paras:
                sections.append((current_heading, current_role, current_paras, current_block_ids))
            current_heading = line.lstrip("#").strip()
            current_role = role_map.get(current_heading, SectionRole.UNKNOWN)
            current_paras = []
            current_block_ids = []
        elif line.strip():
            current_paras.append(line.strip())
            current_block_ids.append(None)

    if current_paras:
        sections.append((current_heading, current_role, current_paras, current_block_ids))

    return sections


def _split_from_block_graph(
    inp: SummaryInput,
    role_map: dict[str, SectionRole],
) -> list[tuple[str, SectionRole, list[str], list[str | None]]]:
    blocks = (inp.block_graph_json or {}).get("blocks") or []
    if not isinstance(blocks, list) or not blocks:
        return []

    toc_title_by_id = {
        node.get("id"): node.get("title")
        for node in (inp.toc_json or [])
        if isinstance(node, dict) and node.get("id") and node.get("title")
    }
    grouped: dict[tuple[str, str], tuple[list[str], list[str | None]]] = {}
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("block_type") == "heading":
            continue
        text = (block.get("text") or "").strip()
        if not text:
            continue
        section_id = block.get("section_id") or ""
        heading = toc_title_by_id.get(section_id, section_id)
        role = role_map.get(heading, SectionRole.UNKNOWN)
        key = (heading, role.value)
        paras, ids = grouped.setdefault(key, ([], []))
        paras.append(text)
        ids.append(block.get("block_id"))

    return [
        (heading, SectionRole(role), paras, ids)
        for (heading, role), (paras, ids) in grouped.items()
        if paras
    ]


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _sentence_salience(sent: str) -> float:
    """Heuristic salience: longer sentences with numbers/claims score higher."""
    score = min(len(sent) / 200, 1.0)
    if re.search(r"\d+\.?\d*\s*%|\d+\.\d+", sent):
        score += 0.2
    if re.search(r"\b(show|demonstrate|find|conclude|reveal|significant)\b", sent, re.I):
        score += 0.15
    if re.search(r"\b(however|although|but|limitation|challenge)\b", sent, re.I):
        score += 0.1
    return min(score, 1.0)
