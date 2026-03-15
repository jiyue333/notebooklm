"""Summary pipeline observability – single file for all instrumentation.

Same Observer-injection pattern as search and ingest pipelines.
Covers ADR-003 §6.1 log points and online metrics.
"""

from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import (
    observe_summary_cache_hit,
    observe_summary_e2e,
    observe_summary_fallback,
    observe_summary_judge_reject,
    observe_summary_route_mix,
    observe_summary_stage,
)
from app.infra.telemetry.tracing import start_span

logger = structlog.get_logger("summary.pipeline")


class SummaryPipelineObserver:
    def __init__(self, article_type: str = "unknown") -> None:
        self._article_type = article_type

    # ── stage lifecycle ────────────────────────────────────────────────

    def on_stage_start(self, stage: str, **extra) -> None:
        logger.info(f"summary.{stage}_started", article_type=self._article_type, **extra)

    def on_stage_complete(self, stage: str, duration_ms: float, *, status: str = "success", **extra) -> None:
        observe_summary_stage(stage=stage, status=status, duration_ms=duration_ms)
        logger.info(
            f"summary.{stage}_done",
            article_type=self._article_type,
            duration_ms=duration_ms,
            **extra,
        )

    def on_stage_error(self, stage: str, duration_ms: float, error: str) -> None:
        observe_summary_stage(stage=stage, status="error", duration_ms=duration_ms)
        logger.error(f"summary.{stage}_error", duration_ms=duration_ms, error=error)

    # ── pipeline-level ─────────────────────────────────────────────────

    def on_pipeline_complete(self, total_ms: float, **extra) -> None:
        observe_summary_e2e(duration_ms=total_ms)
        logger.info("summary.pipeline_complete", total_ms=total_ms, **extra)

    def on_pipeline_error(self, total_ms: float, error: str) -> None:
        observe_summary_e2e(duration_ms=total_ms)
        logger.error("summary.pipeline_error", total_ms=total_ms, error=error)

    # ── domain signals ─────────────────────────────────────────────────

    def on_profiled(self, article_type: str) -> None:
        self._article_type = article_type
        logger.info("summary.profiled", article_type=article_type)

    def on_route_selected(self, route: str) -> None:
        observe_summary_route_mix(route=route)
        logger.info("summary.route_selected", route=route)

    def on_evidence_extracted(self, count: int) -> None:
        logger.info("summary.evidence_extracted", count=count)

    def on_candidate_generated(self, style: str) -> None:
        logger.info("summary.candidate_generated", style=style)

    def on_judge_done(self, winner_style: str, score: float) -> None:
        logger.info("summary.judge_done", winner=winner_style, score=score)

    def on_judge_reject(self, reason: str) -> None:
        observe_summary_judge_reject(reason=reason)
        logger.warning("summary.judge_reject", reason=reason)

    def on_finalized(self) -> None:
        logger.info("summary.finalized")

    def on_fallback_triggered(self, trigger: str) -> None:
        observe_summary_fallback(trigger=trigger)
        logger.warning("summary.fallback_triggered", trigger=trigger)

    def on_cache_hit(self) -> None:
        observe_summary_cache_hit()
        logger.info("summary.cache_hit")

    def span(self, name: str, **extra_attrs):
        return start_span(f"summary.{name}", attributes=extra_attrs)
