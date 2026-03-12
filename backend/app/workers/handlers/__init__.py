from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from app.infra.telemetry.metrics import observe_job
from app.modules.ingest.worker_handler import (
    process_article_ingest,
    process_article_reindex,
    process_search_deep,
)

logger = structlog.get_logger(__name__)

JobProcessor = Callable[[str], Awaitable[None]]


def _build_job_handler(*, job_type: str, log_event: str, processor: JobProcessor):
    async def _handler(payload: dict) -> None:
        observe_job(job_type=job_type, status="received")
        logger.info(log_event, payload=payload)
        await processor(payload["jobId"])

    return _handler


handle_article_ingest = _build_job_handler(
    job_type="article_ingest",
    log_event="worker.article_ingest.received",
    processor=process_article_ingest,
)
handle_article_reindex = _build_job_handler(
    job_type="article_reindex",
    log_event="worker.article_reindex.received",
    processor=process_article_reindex,
)
handle_search_deep = _build_job_handler(
    job_type="search_deep",
    log_event="worker.search_deep.received",
    processor=process_search_deep,
)

__all__ = [
    "handle_article_ingest",
    "handle_article_reindex",
    "handle_search_deep",
]
