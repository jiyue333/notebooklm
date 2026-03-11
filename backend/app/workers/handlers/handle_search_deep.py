from __future__ import annotations

import structlog

from app.infra.telemetry.metrics import observe_job
from app.modules.ingest.worker_handler import process_search_deep

logger = structlog.get_logger(__name__)


async def handle_search_deep(payload: dict) -> None:
    observe_job(job_type="search_deep", status="received")
    logger.info("worker.search_deep.received", payload=payload)
    await process_search_deep(payload["jobId"])
