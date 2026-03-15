"""Stage C – Length & Quality Routing.

Selects one of four summary routes based on article length and
parse quality (ADR-003 §4.4):

  S – short / high structure  → direct summary
  M – medium                  → section micro-summary + merge
  L – long                    → hierarchical summary
  X – poor parse quality      → conservative safe summary
"""

from __future__ import annotations

from app.modules.ai.summary.pipeline.types import (
    ArticleProfile,
    StructureQuality,
    SummaryInput,
    SummaryRoute,
)

_SHORT_THRESHOLD = 1500   # words
_MEDIUM_THRESHOLD = 5000  # words


def select_route(
    inp: SummaryInput,
    profile: ArticleProfile,
) -> SummaryRoute:
    if profile.structure_quality == StructureQuality.LOW and inp.quality_score < 0.35:
        return SummaryRoute.X

    wc = profile.word_count or len(inp.clean_markdown.split())

    if wc <= _SHORT_THRESHOLD:
        return SummaryRoute.S
    if wc <= _MEDIUM_THRESHOLD:
        return SummaryRoute.M
    return SummaryRoute.L
