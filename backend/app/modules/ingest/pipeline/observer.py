"""Ingest pipeline observability – single file for all instrumentation.

Same pattern as search/pipeline/observer.py: an observer injected into
the pipeline orchestrator.  All Prometheus, structlog and OTel code
lives here so pipeline stages and the service layer stay clean.

ADR-002 §6.1 log points and online metrics.
"""

from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import (
    observe_ingest_block_completeness,
    observe_ingest_e2e,
    observe_ingest_fallback_rate,
    observe_ingest_fetch_latency,
    observe_ingest_parse_success,
    observe_ingest_route_distribution,
    observe_ingest_stage,
    observe_ingest_synthetic_toc,
)
from app.infra.telemetry.tracing import start_span

logger = structlog.get_logger("ingest.pipeline")


class IngestPipelineObserver:
    """Injected into ``run_pipeline``; receives events at stage boundaries."""

    def __init__(self, input_type: str) -> None:
        self._input_type = input_type
        self._span_attrs = {"ingest.input_type": input_type}

    # ── stage lifecycle ────────────────────────────────────────────────

    def on_stage_start(self, stage: str, **extra) -> None:
        logger.info(f"ingest.{stage}_started", input_type=self._input_type, **extra)

    def on_stage_complete(
        self,
        stage: str,
        duration_ms: float,
        *,
        status: str = "success",
        **extra,
    ) -> None:
        observe_ingest_stage(
            stage=stage, input_type=self._input_type, status=status, duration_ms=duration_ms,
        )
        logger.info(
            f"ingest.{stage}_done",
            input_type=self._input_type,
            duration_ms=duration_ms,
            status=status,
            **extra,
        )

    def on_stage_error(self, stage: str, duration_ms: float, error: str) -> None:
        observe_ingest_stage(
            stage=stage, input_type=self._input_type, status="error", duration_ms=duration_ms,
        )
        logger.error(
            f"ingest.{stage}_error",
            input_type=self._input_type,
            duration_ms=duration_ms,
            error=error,
        )

    # ── pipeline-level events ──────────────────────────────────────────

    def on_pipeline_complete(self, total_ms: float, **extra) -> None:
        observe_ingest_e2e(input_type=self._input_type, duration_ms=total_ms)
        logger.info(
            "ingest.pipeline_complete",
            input_type=self._input_type,
            total_ms=total_ms,
            **extra,
        )

    def on_pipeline_error(self, total_ms: float, error: str) -> None:
        observe_ingest_e2e(input_type=self._input_type, duration_ms=total_ms)
        logger.error(
            "ingest.pipeline_error",
            input_type=self._input_type,
            total_ms=total_ms,
            error=error,
        )

    # ── domain-specific signals ────────────────────────────────────────

    def on_fetch_complete(self, duration_ms: float, content_type: str) -> None:
        observe_ingest_fetch_latency(
            input_type=self._input_type, content_type=content_type, duration_ms=duration_ms,
        )

    def on_type_routed(self, category: str) -> None:
        observe_ingest_route_distribution(input_type=self._input_type, category=category)
        logger.info("ingest.type_routed", input_type=self._input_type, category=category)

    def on_parse_candidate_generated(self, parser_name: str, success: bool) -> None:
        observe_ingest_parse_success(
            input_type=self._input_type, parser=parser_name,
            result="success" if success else "failure",
        )
        logger.info(
            "ingest.parse_candidate_generated",
            input_type=self._input_type,
            parser=parser_name,
            success=success,
        )

    def on_parse_scored(self, parser_name: str, score: float) -> None:
        logger.info(
            "ingest.parse_scored",
            input_type=self._input_type,
            parser=parser_name,
            score=score,
        )

    def on_parse_selected(self, parser_name: str, score: float) -> None:
        logger.info(
            "ingest.parse_selected",
            input_type=self._input_type,
            parser=parser_name,
            score=score,
        )

    def on_fallback_triggered(self, trigger: str) -> None:
        observe_ingest_fallback_rate(input_type=self._input_type, trigger=trigger)
        logger.warning("ingest.fallback_triggered", input_type=self._input_type, trigger=trigger)

    def on_toc_generated(self, count: int, is_synthetic: bool) -> None:
        observe_ingest_synthetic_toc(
            input_type=self._input_type,
            result="synthetic" if is_synthetic else "extracted",
        )
        logger.info(
            "ingest.toc_generated",
            input_type=self._input_type,
            node_count=count,
            is_synthetic=is_synthetic,
        )

    def on_block_graph_built(self, block_counts: dict[str, int]) -> None:
        total = sum(block_counts.values())
        if total > 0:
            for bt, cnt in block_counts.items():
                observe_ingest_block_completeness(
                    input_type=self._input_type, block_type=bt, count=cnt,
                )
        logger.info(
            "ingest.block_graph_built",
            input_type=self._input_type,
            block_counts=block_counts,
        )

    def on_anchor_bound(self, count: int) -> None:
        logger.info("ingest.anchor_bound", input_type=self._input_type, anchor_count=count)

    # ── OTel span helper ───────────────────────────────────────────────

    def span(self, name: str, **extra_attrs):
        attrs = {**self._span_attrs, **extra_attrs}
        return start_span(f"ingest.{name}", attributes=attrs)
