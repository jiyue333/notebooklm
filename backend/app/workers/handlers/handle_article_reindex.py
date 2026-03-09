from __future__ import annotations

import asyncio
import structlog

from app.infra.telemetry.metrics import observe_job
from app.modules.ingest.worker_handler import process_article_reindex

logger = structlog.get_logger(__name__)


def handle_article_reindex(payload: dict) -> None:
    observe_job(job_type="article_reindex", status="received")
    logger.info("worker.article_reindex.received", payload=payload)
    asyncio.run(process_article_reindex(payload["jobId"]))
