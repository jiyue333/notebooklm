from __future__ import annotations

import asyncio
import structlog

from app.infra.telemetry.metrics import observe_job
from app.modules.ingest.worker_handler import process_article_ingest

logger = structlog.get_logger(__name__)


def handle_article_ingest(payload: dict) -> None:
    observe_job(job_type="article_ingest", status="received")
    logger.info("worker.article_ingest.received", payload=payload)
    asyncio.run(process_article_ingest(payload["jobId"]))
