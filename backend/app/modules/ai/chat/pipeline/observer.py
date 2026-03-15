"""Chat pipeline observability – single file for all instrumentation.

Covers ADR-004 §6.1 log points and online metrics.
"""

from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import (
    observe_chat_e2e,
    observe_chat_evidence_coverage,
    observe_chat_fallback,
    observe_chat_retrieval,
    observe_chat_route_mix,
    observe_chat_stage,
)
from app.infra.telemetry.tracing import start_span

logger = structlog.get_logger("chat.pipeline")


class ChatPipelineObserver:
    def __init__(self, route: str = "unknown") -> None:
        self._route = route

    def on_stage_start(self, stage: str, **extra) -> None:
        logger.info(f"chat.{stage}_started", route=self._route, **extra)

    def on_stage_complete(self, stage: str, duration_ms: float, *, status: str = "success", **extra) -> None:
        route = extra.get("route", self._route)
        observe_chat_stage(stage=stage, route=route, status=status, duration_ms=duration_ms)
        logger.info(f"chat.{stage}_done", route=self._route, duration_ms=duration_ms, **extra)

    def on_stage_error(self, stage: str, duration_ms: float, error: str) -> None:
        observe_chat_stage(stage=stage, route=self._route, status="error", duration_ms=duration_ms)
        logger.error(f"chat.{stage}_error", route=self._route, duration_ms=duration_ms, error=error)

    def on_pipeline_complete(self, total_ms: float, **extra) -> None:
        observe_chat_e2e(duration_ms=total_ms)
        logger.info("chat.pipeline_complete", route=self._route, total_ms=total_ms, **extra)

    def on_pipeline_error(self, total_ms: float, error: str) -> None:
        observe_chat_e2e(duration_ms=total_ms)
        logger.error("chat.pipeline_error", route=self._route, total_ms=total_ms, error=error)

    def on_route_selected(self, route: str, confidence: float) -> None:
        self._route = route
        observe_chat_route_mix(route=route)
        logger.info("chat.route_selected", route=route, confidence=confidence)

    def on_retrieval_done(self, evidence_count: int, recommendation_count: int) -> None:
        observe_chat_retrieval(
            route=self._route,
            evidence_count=evidence_count,
            recommendation_count=recommendation_count,
        )
        logger.info(
            "chat.retrieval_done",
            route=self._route,
            evidence_count=evidence_count,
            recommendation_count=recommendation_count,
        )

    def on_answer_generated(self) -> None:
        logger.info("chat.answer_generated", route=self._route)

    def on_verified(self, is_verified: bool, coverage: float) -> None:
        observe_chat_evidence_coverage(route=self._route, coverage=coverage)
        logger.info("chat.verified", route=self._route, is_verified=is_verified, coverage=coverage)

    def on_fallback_triggered(self, reason: str) -> None:
        observe_chat_fallback(reason=reason)
        logger.warning("chat.fallback_triggered", route=self._route, reason=reason)

    def on_response_served(self) -> None:
        logger.info("chat.response_served", route=self._route)

    def span(self, name: str, **extra_attrs):
        return start_span(f"chat.{name}", attributes={"chat.route": self._route, **extra_attrs})
