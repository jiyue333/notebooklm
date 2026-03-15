"""Stage E – Final Output.

Assembles the winning summary candidate, evidence spans, and profile
tags into an ``ArticleSummary`` ready for caching and display.
"""

from __future__ import annotations

from app.modules.ai.summary.prompts import PROMPT_VERSION
from app.modules.ai.summary.pipeline.types import (
    ArticleProfile,
    ArticleSummary,
    EvidenceBullet,
    EvidenceSpan,
    ScoredSummaryCandidate,
    SummaryRoute,
)


def build_output(
    winner: ScoredSummaryCandidate,
    profile: ArticleProfile,
    evidence: list[EvidenceBullet],
    route: SummaryRoute,
) -> ArticleSummary:
    """Construct the final ``ArticleSummary``."""

    selected_indexes = winner.candidate.evidence_bullet_ids or list(range(len(evidence)))
    spans = [
        EvidenceSpan(
            bullet_text=evidence[index].text,
            block_ids=evidence[index].block_ids,
            role=evidence[index].role.value,
        )
        for index in selected_indexes
        if 0 <= index < len(evidence)
    ]

    tags = {
        "article_type": profile.article_type.value,
        "evidence_style": profile.evidence_style.value,
        "structure_quality": profile.structure_quality.value,
        "domain": profile.domain,
    }

    return ArticleSummary(
        summary_text=winner.candidate.text,
        summary_type="canonical",
        evidence_spans=spans,
        profile_tags=tags,
        confidence=winner.scores.total,
        prompt_version=PROMPT_VERSION,
        route=route,
    )
