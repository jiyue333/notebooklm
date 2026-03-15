"""Search pipeline observability – the SINGLE file for all instrumentation.

Implements an observer that the pipeline orchestrator calls at stage
boundaries.  All Prometheus metrics, structlog events and OTel spans
live here so the pipeline and service layers stay free of telemetry
imports.

ADR-001 §6.1 log points:
  search.task_parsed, search.query_family_generated, search.recall_started,
  search.recall_done, search.canonicalized, search.enrichment_started,
  search.enrichment_done, search.rerank_done, search.slate_served,
  search.fallback_triggered

ADR-001 §6.1 online metrics:
  E2E p50/p95/p99, Recall fan-out p50/p95, Partial failure rate,
  Enrichment timeout rate, Dedup hit rate, Empty/low-confidence slate,
  Authority@10, Diversity@10, Novelty@10
"""

from __future__ import annotations

import math
from collections import Counter

import structlog

from app.infra.telemetry.metrics import (
    observe_search_authority_proxy,
    observe_search_dedup,
    observe_search_diversity_proxy,
    observe_search_e2e,
    observe_search_empty_slate,
    observe_search_novelty_proxy,
    observe_search_partial_failure,
    observe_search_slate_card_count,
    observe_search_stage,
)
from app.infra.telemetry.tracing import start_span

logger = structlog.get_logger("search.pipeline")


class SearchPipelineObserver:
    """Injected into ``run_pipeline``; receives events at stage boundaries."""

    def __init__(self, mode: str) -> None:
        self._mode = mode
        self._span_attrs = {"search.mode": mode}

    # ── stage lifecycle ────────────────────────────────────────────────

    def on_stage_start(self, stage: str, **extra) -> None:
        logger.info(f"search.{stage}_started", mode=self._mode, **extra)

    def on_stage_complete(
        self,
        stage: str,
        duration_ms: float,
        *,
        status: str = "success",
        **extra,
    ) -> None:
        observe_search_stage(
            stage=stage, mode=self._mode, status=status, duration_ms=duration_ms,
        )
        logger.info(
            f"search.{stage}_done",
            mode=self._mode,
            duration_ms=duration_ms,
            status=status,
            **extra,
        )

    def on_stage_error(self, stage: str, duration_ms: float, error: str) -> None:
        observe_search_stage(
            stage=stage, mode=self._mode, status="error", duration_ms=duration_ms,
        )
        logger.error(
            f"search.{stage}_error",
            mode=self._mode,
            duration_ms=duration_ms,
            error=error,
        )

    # ── pipeline-level events ──────────────────────────────────────────

    def on_pipeline_complete(self, total_ms: float, card_count: int) -> None:
        observe_search_e2e(mode=self._mode, duration_ms=total_ms)
        observe_search_slate_card_count(mode=self._mode, count=card_count)
        logger.info(
            "search.pipeline_complete",
            mode=self._mode,
            total_ms=total_ms,
            card_count=card_count,
        )

    def on_pipeline_error(self, total_ms: float, error: str) -> None:
        observe_search_e2e(mode=self._mode, duration_ms=total_ms)
        logger.error(
            "search.pipeline_error",
            mode=self._mode,
            total_ms=total_ms,
            error=error,
        )

    # ── domain-specific signals ────────────────────────────────────────

    def on_recall_partial_failure(self, failed_roles: list[str]) -> None:
        observe_search_partial_failure(mode=self._mode)
        logger.warning(
            "search.recall_partial_failure",
            mode=self._mode,
            failed_roles=failed_roles,
        )

    def on_dedup(self, *, before: int, after: int) -> None:
        removed = before - after
        if removed > 0:
            observe_search_dedup(mode=self._mode, dedup_type="total", count=removed)
        logger.info(
            "search.canonicalized",
            mode=self._mode,
            before=before,
            after=after,
            removed=removed,
        )

    def on_empty_slate(self, reason: str = "no_results") -> None:
        observe_search_empty_slate(mode=self._mode, reason=reason)
        logger.warning("search.empty_slate", mode=self._mode, reason=reason)

    def on_fallback_triggered(self, trigger: str) -> None:
        logger.warning("search.fallback_triggered", mode=self._mode, trigger=trigger)

    def on_slate_quality(self, cards: list) -> None:
        """Compute and report slate-level quality proxy metrics (ADR-001 §6.1).

        Operates on the final ``SearchCard`` list.  Accepts ``list``
        (not typed) so the observer stays decoupled from pipeline types.
        """
        if not cards:
            return
        top10 = cards[:10]
        n = len(top10)

        # Authority proxy@10
        tier1_count = sum(
            1 for c in top10
            if getattr(c, "authority_badge", None) is not None
        )
        observe_search_authority_proxy(mode=self._mode, ratio=tier1_count / n)

        # Diversity proxy@10 – Shannon entropy of source_type_badge
        type_counts = Counter(getattr(c, "source_type_badge", "other") for c in top10)
        entropy = _shannon_entropy(type_counts, n)
        observe_search_diversity_proxy(mode=self._mode, entropy=entropy)

        # Novelty proxy@10 – fraction with import_suggestion != duplicate_risk
        novel = sum(
            1 for c in top10
            if str(getattr(c, "import_suggestion", "optional")) != "duplicate_risk"
        )
        observe_search_novelty_proxy(mode=self._mode, ratio=novel / n)

    # ── OTel span helper ───────────────────────────────────────────────

    def span(self, name: str, **extra_attrs):
        """Return an OTel span context manager scoped to this search."""
        attrs = {**self._span_attrs, **extra_attrs}
        return start_span(f"search.{name}", attributes=attrs)


# ── utility ────────────────────────────────────────────────────────────────

def _shannon_entropy(counts: Counter, total: int) -> float:
    """Normalised Shannon entropy ∈ [0, 1]."""
    if total == 0 or len(counts) <= 1:
        return 0.0
    raw = -sum(
        (c / total) * math.log2(c / total)
        for c in counts.values() if c > 0
    )
    max_entropy = math.log2(len(counts))
    return raw / max_entropy if max_entropy > 0 else 0.0
