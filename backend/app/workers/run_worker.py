from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import structlog

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.mq.consumer import KafkaConsumer
from app.infra.mq.topics import (
    NOTEBOOK_ASYNC_TOPIC,
    TAG_ARTICLE_INGEST,
    TAG_ARTICLE_REINDEX,
    TAG_SEARCH_DEEP,
)
from app.infra.telemetry.langsmith import configure_langsmith
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.metrics import ensure_metrics_server
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.workers.handlers import (
    handle_article_ingest,
    handle_article_reindex,
    handle_search_deep,
)

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)
    ensure_metrics_server(port=settings.worker_metrics_port)
    setup_tracing(engine=get_session_manager().engine, settings=settings)

    consumer = KafkaConsumer(
        group_id="notebooklm-worker",
        topic=settings.kafka_topic or NOTEBOOK_ASYNC_TOPIC,
        poll_timeout_ms=settings.kafka_consumer_poll_timeout_ms,
    )
    consumer.register_handler(TAG_SEARCH_DEEP, handle_search_deep)
    consumer.register_handler(TAG_ARTICLE_INGEST, handle_article_ingest)
    consumer.register_handler(TAG_ARTICLE_REINDEX, handle_article_reindex)
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
    logger.info(
        "worker.started",
        topic=settings.kafka_topic or NOTEBOOK_ASYNC_TOPIC,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        consumer_available=consumer_available,
    )

    stop_event = asyncio.Event()
    if consumer_available:
        consumer_task = asyncio.create_task(
            consumer.poll_loop(),
            name="kafka-poll",
        )

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
