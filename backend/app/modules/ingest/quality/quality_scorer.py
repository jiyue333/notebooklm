from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ParseQuality:
    score: float
    needs_llm_fallback: bool


def score_markdown(markdown: str) -> ParseQuality:
    text = markdown.strip()
    if not text:
        return ParseQuality(score=0.0, needs_llm_fallback=True)

    length_score = min(len(text) / 4000, 1.0) * 60
    heading_score = min(markdown.count("\n#"), 6) * 5
    penalty = 20 if "\ufffd" in markdown else 0
    score = max(length_score + heading_score - penalty, 0.0)
    needs_llm_fallback = score < 35
    return ParseQuality(score=round(score, 2), needs_llm_fallback=needs_llm_fallback)
