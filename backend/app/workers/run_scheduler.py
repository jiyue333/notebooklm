from __future__ import annotations

import asyncio
import signal

import structlog

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.telemetry.langsmith import configure_langsmith
from app.infra.telemetry.logging import setup_logging
from app.infra.telemetry.metrics_server import ensure_metrics_server
from app.infra.telemetry.tracing import setup_tracing, shutdown_tracing
from app.modules.jobs.scheduler import run_scheduler_tick

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
    configure_langsmith(settings)
    ensure_metrics_server(port=settings.scheduler_metrics_port)
    setup_tracing(engine=get_session_manager().engine, settings=settings)
    stop_event = asyncio.Event()

    def shutdown_handler(signum, _frame) -> None:
        logger.info("scheduler.stopping", signal=signum)
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("scheduler.started")
    while not stop_event.is_set():
        stats = await run_scheduler_tick()
        logger.info("scheduler.tick", **stats)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=15.0)
        except TimeoutError:
            continue

    logger.info("scheduler.stopped")
    shutdown_tracing()


if __name__ == "__main__":
    asyncio.run(main())
