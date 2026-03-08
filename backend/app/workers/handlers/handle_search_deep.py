from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import observe_job

logger = structlog.get_logger(__name__)


def handle_search_deep(payload: dict) -> None:
    observe_job(job_type="search_deep", status="received")
    logger.info("worker.search_deep.received", payload=payload)
