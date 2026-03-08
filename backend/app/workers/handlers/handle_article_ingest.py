from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import observe_job

logger = structlog.get_logger(__name__)


def handle_article_ingest(payload: dict) -> None:
    observe_job(job_type="article_ingest", status="received")
    logger.info("worker.article_ingest.received", payload=payload)
