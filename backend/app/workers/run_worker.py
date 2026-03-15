"""Kafka worker process.

Consumes article_ingest jobs from the message queue and runs the
ingest pipeline asynchronously.
"""

from __future__ import annotations

import asyncio
import faulthandler
import os
import resource
import signal
from contextlib import suppress

import structlog

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.mq.consumer import KafkaConsumer
from app.infra.mq.topics import NOTEBOOK_ASYNC_TOPIC, TAG_ARTICLE_INGEST, TAG_SEARCH_DEEP
from app.infra.telemetry.langsmith import configure_langsmith
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.metrics import ensure_metrics_server
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.workers.handlers import handle_article_ingest, handle_search_deep

logger = structlog.get_logger(__name__)


def _log_memory(label: str = "") -> None:
    rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if os.uname().sysname == "Darwin":
        rss_mb = rss_bytes / (1024 * 1024)
    else:
        rss_mb = rss_bytes / 1024
    logger.info("worker.memory", rss_mb=round(rss_mb, 1), label=label, pid=os.getpid())


async def main() -> None:
    faulthandler.enable()
    if hasattr(faulthandler, "register"):
        faulthandler.register(signal.SIGUSR1, all_threads=True)

    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)
    try:
        ensure_metrics_server(port=settings.worker_metrics_port)
    except Exception as exc:
        logger.warning("worker.metrics_server_failed", error=str(exc))
    setup_tracing(engine=get_session_manager().engine, settings=settings)

    consumer = KafkaConsumer(
        group_id="notebooklm-worker",
        topic=settings.kafka_topic or NOTEBOOK_ASYNC_TOPIC,
        poll_timeout_ms=settings.kafka_consumer_poll_timeout_ms,
    )
    consumer.register_handler(TAG_ARTICLE_INGEST, handle_article_ingest)
    consumer.register_handler(TAG_SEARCH_DEEP, handle_search_deep)

    consumer_available = True
    consumer_task: asyncio.Task[None] | None = None
    try:
        await consumer.start()
    except ImportError as exc:
        consumer_available = False
        logger.warning("worker.consumer_unavailable", error=str(exc))
    except Exception as exc:
        consumer_available = False
        logger.exception("worker.consumer_start_failed", error=str(exc))

    _log_memory("after_startup")
    logger.info(
        "worker.started",
        topic=settings.kafka_topic or NOTEBOOK_ASYNC_TOPIC,
        consumer_available=consumer_available,
    )

    stop_event = asyncio.Event()

    def _on_consumer_task_done(task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("worker.consumer_task_crashed", error=str(exc))
        else:
            logger.warning("worker.consumer_task_exited_unexpectedly")
        stop_event.set()

    if consumer_available:
        consumer_task = asyncio.create_task(consumer.poll_loop(), name="kafka-poll")
        consumer_task.add_done_callback(_on_consumer_task_done)

    def shutdown_handler(signum, _frame) -> None:
        logger.info("worker.stopping", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        await stop_event.wait()
    finally:
        if consumer_available:
            consumer.request_shutdown()
        if consumer_task is not None:
            try:
                await asyncio.wait_for(consumer_task, timeout=5)
            except TimeoutError:
                consumer_task.cancel()
                with suppress(asyncio.CancelledError):
                    await consumer_task
            finally:
                await consumer.shutdown()
        shutdown_tracing()
        logger.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())
