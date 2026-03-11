from __future__ import annotations

import signal
import threading

import structlog

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.mq.consumer import RocketMQConsumer
from app.infra.mq.topics import (
    NOTEBOOK_ASYNC_TOPIC,
    TAG_ARTICLE_INGEST,
    TAG_ARTICLE_REINDEX,
    TAG_SEARCH_DEEP,
)
from app.infra.telemetry.langsmith import configure_langsmith
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.metrics_server import ensure_metrics_server
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.workers.handlers.handle_article_ingest import handle_article_ingest
from app.workers.handlers.handle_article_reindex import handle_article_reindex
from app.workers.handlers.handle_search_deep import handle_search_deep

logger = structlog.get_logger(__name__)


def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)
    ensure_metrics_server(port=settings.worker_metrics_port)

    consumer = RocketMQConsumer(
        group_id="notebooklm-worker",
        topic=settings.rocketmq_topic or NOTEBOOK_ASYNC_TOPIC,
        invisible_duration=settings.rocketmq_consumer_invisible_duration_seconds,
    )
    consumer.register_handler(TAG_SEARCH_DEEP, handle_search_deep)
    consumer.register_handler(TAG_ARTICLE_INGEST, handle_article_ingest)
    consumer.register_handler(TAG_ARTICLE_REINDEX, handle_article_reindex)
    consumer_available = True
    try:
        consumer.start()
    except ImportError as exc:
        consumer_available = False
        logger.warning("worker.consumer_unavailable", error=str(exc))
    logger.info(
        "worker.started",
        topic=settings.rocketmq_topic or NOTEBOOK_ASYNC_TOPIC,
        consumer_available=consumer_available,
    )

    stop_event = threading.Event()

    # Start the poll loop in a background thread
    poll_thread: threading.Thread | None = None
    if consumer_available:
        def run_consumer_loop() -> None:
            setup_tracing(engine=get_session_manager().engine, settings=settings)
            consumer.poll_loop()

        poll_thread = threading.Thread(
            target=run_consumer_loop, name="mq-poll", daemon=True
        )
        poll_thread.start()

    def shutdown_handler(signum, _frame) -> None:
        logger.info("worker.stopping", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        stop_event.wait()
    finally:
        if consumer_available:
            consumer.shutdown()
        if poll_thread is not None:
            poll_thread.join(timeout=5)
        shutdown_tracing()
        logger.info("worker.stopped")


if __name__ == "__main__":
    main()
