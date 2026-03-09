from __future__ import annotations

import signal
import threading

import structlog

from app.core.config import get_settings
from app.infra.mq.consumer import RocketMQConsumer
from app.infra.db.session import get_session_manager
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
    setup_tracing(engine=get_session_manager().engine, settings=settings)

    consumer = RocketMQConsumer(
        group_id="notebooklm-worker",
        topic=settings.rocketmq_topic or NOTEBOOK_ASYNC_TOPIC,
    )
    consumer.register_handler(TAG_SEARCH_DEEP, handle_search_deep)
    consumer.register_handler(TAG_ARTICLE_INGEST, handle_article_ingest)
    consumer.register_handler(TAG_ARTICLE_REINDEX, handle_article_reindex)
    consumer.start()
    logger.info("worker.started", topic=settings.rocketmq_topic or NOTEBOOK_ASYNC_TOPIC)

    stop_event = threading.Event()

    def shutdown_handler(signum, _frame) -> None:
        logger.info("worker.stopping", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        stop_event.wait()
    finally:
        consumer.shutdown()
        shutdown_tracing()
        logger.info("worker.stopped")


if __name__ == "__main__":
    main()
