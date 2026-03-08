from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import observe_job

logger = structlog.get_logger(__name__)


def handle_cleanup(payload: dict) -> None:
    observe_job(job_type="maintenance_cleanup", status="received")
    logger.info("worker.maintenance_cleanup.received", payload=payload)
