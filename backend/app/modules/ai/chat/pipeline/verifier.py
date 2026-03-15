"""Stage D – Verification & Fallback.

Checks the draft answer for evidence coverage and scope consistency.
Triggers fallback when quality is insufficient.
"""

from __future__ import annotations

from app.modules.ai.chat.pipeline.types import (
    ChatRoute,
    DraftAnswer,
    FallbackReason,
    RetrievalResult,
    RouteDecision,
    VerifiedAnswer,
)


def verify(
    draft: DraftAnswer,
    decision: RouteDecision,
    retrieval: RetrievalResult,
) -> VerifiedAnswer:
    """Run verification checks and attach fallback metadata."""

    evidence_coverage = _compute_evidence_coverage(draft, retrieval)
    fallback_reason = _check_fallback(draft, decision, retrieval, evidence_coverage)

    if fallback_reason != FallbackReason.NONE:
        patched = _apply_fallback(draft, fallback_reason)
        return VerifiedAnswer(
            answer=patched,
            is_verified=False,
            fallback_used=True,
            fallback_reason=fallback_reason,
            evidence_coverage=evidence_coverage,
            confidence=decision.confidence * 0.5,
        )

    return VerifiedAnswer(
        answer=draft,
        is_verified=True,
        fallback_used=False,
        fallback_reason=FallbackReason.NONE,
        evidence_coverage=evidence_coverage,
        confidence=decision.confidence,
    )


def _compute_evidence_coverage(draft: DraftAnswer, retrieval: RetrievalResult) -> float:
    if draft.route == ChatRoute.GENERAL:
        return 1.0  # general answers don't need local evidence

    total_evidence = len(retrieval.evidence_chunks) + len(retrieval.recommended_articles)
    cited = len(draft.evidence_spans) + len(draft.related_articles)
    if total_evidence == 0:
        return 0.0
    return min(cited / max(total_evidence, 1), 1.0)


def _check_fallback(
    draft: DraftAnswer,
    decision: RouteDecision,
    retrieval: RetrievalResult,
    coverage: float,
) -> FallbackReason:
    # Unstable route
    if decision.confidence < 0.3 and decision.shadow_route is not None:
        return FallbackReason.UNSTABLE_ROUTE

    # Insufficient evidence for article-grounded
    if draft.route == ChatRoute.ARTICLE_GROUNDED and not retrieval.evidence_chunks:
        return FallbackReason.INSUFFICIENT_EVIDENCE

    # Low similarity for recommendations
    if draft.route == ChatRoute.RECOMMENDATION and not retrieval.recommended_articles:
        return FallbackReason.LOW_SIMILARITY

    # Notebook research with no clusters
    if draft.route == ChatRoute.NOTEBOOK_RESEARCH and not retrieval.evidence_clusters:
        return FallbackReason.INSUFFICIENT_EVIDENCE

    return FallbackReason.NONE


def _apply_fallback(draft: DraftAnswer, reason: FallbackReason) -> DraftAnswer:
    """Patch the draft answer with a fallback disclaimer."""

    disclaimers = {
        FallbackReason.INSUFFICIENT_EVIDENCE: (
            "\n\n---\n*注意：当前文章/笔记本中的证据不足以完全回答此问题。"
            "以上回答可能不够全面。*"
        ),
        FallbackReason.LOW_SIMILARITY: (
            "\n\n---\n*注意：未找到高度相似的文章，以上结果为弱相关候选。*"
        ),
        FallbackReason.EVIDENCE_CONFLICT: (
            "\n\n---\n*注意：笔记本内的资料存在观点分歧，请留意不同来源的立场差异。*"
        ),
        FallbackReason.UNSTABLE_ROUTE: (
            "\n\n---\n*注意：问题意图尚不确定，当前按最可能的方向回答。"
            "如果不符合您的需求，请尝试更明确地提问。*"
        ),
    }

    suffix = disclaimers.get(reason, "")
    return DraftAnswer(
        route=draft.route,
        answer_text=draft.answer_text + suffix,
        evidence_spans=draft.evidence_spans,
        related_articles=draft.related_articles,
        route_badge=draft.route_badge,
        metadata={**draft.metadata, "fallback_reason": reason.value},
    )
