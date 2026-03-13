from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParseQuality:
    score: float
    needs_llm_fallback: bool
    structure_scores: dict[str, float] = field(default_factory=dict)


def score_markdown(markdown: str) -> ParseQuality:
    text = markdown.strip()
    if not text:
        return ParseQuality(
            score=0.0,
            needs_llm_fallback=True,
            structure_scores=_empty_structure_scores(),
        )

    structure_scores = {
        "title_hierarchy": _score_title_hierarchy(markdown),
        "list": _score_lists(markdown),
        "table": _score_tables(markdown),
        "image": _score_images(markdown),
        "link": _score_links(markdown),
    }

    length_score = min(len(text) / 4000, 1.0) * 0.45
    heading_score = min(markdown.count("\n#"), 6) / 6 * 0.2
    structure_component = sum(structure_scores.values()) / max(len(structure_scores), 1) * 0.3
    link_density_bonus = 0.05 if structure_scores["link"] > 0 else 0.0
    penalty = 0.2 if "\ufffd" in markdown else 0.0
    score = max(length_score + heading_score + structure_component + link_density_bonus - penalty, 0.0)
    needs_llm_fallback = score < 0.35
    return ParseQuality(
        score=round(min(score, 1.0), 4),
        needs_llm_fallback=needs_llm_fallback,
        structure_scores={key: round(value, 4) for key, value in structure_scores.items()},
    )


def _score_title_hierarchy(markdown: str) -> float:
    headings = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        parts = stripped.split(" ", 1)
        if len(parts) != 2:
            continue
        level = len(parts[0])
        if 1 <= level <= 4:
            headings.append(level)
    if not headings:
        return 0.0
    depth_score = min(len(headings) / 6, 1.0)
    transitions = 0
    stable = 0
    previous = headings[0]
    for level in headings[1:]:
        transitions += 1
        if abs(level - previous) <= 1:
            stable += 1
        previous = level
    stability = 1.0 if transitions == 0 else stable / transitions
    return min(depth_score * 0.6 + stability * 0.4, 1.0)


def _score_lists(markdown: str) -> float:
    list_lines = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if re.match(r"^([-*+]|\d+\.)\s+", stripped):
            list_lines += 1
    return min(list_lines / 6, 1.0)


def _score_tables(markdown: str) -> float:
    has_separator = False
    pipe_lines = 0
    for line in markdown.splitlines():
        stripped = line.strip()
        if "|" in stripped:
            pipe_lines += 1
        if re.match(r"^\|?[\s:-]+\|[\s|:-]*$", stripped):
            has_separator = True
    if pipe_lines >= 2 and has_separator:
        return min(pipe_lines / 4, 1.0)
    return 0.0


def _score_images(markdown: str) -> float:
    image_count = markdown.count("![")
    return min(image_count / 2, 1.0)


def _score_links(markdown: str) -> float:
    link_matches = re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", markdown)
    return min(len(link_matches) / 4, 1.0)


def _empty_structure_scores() -> dict[str, float]:
    return {
        "title_hierarchy": 0.0,
        "list": 0.0,
        "table": 0.0,
        "image": 0.0,
        "link": 0.0,
    }
