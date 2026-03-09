from __future__ import annotations

import asyncio
import signal

import structlog

from app.infra.telemetry.logging import setup_logging
from app.core.config import get_settings
from app.modules.jobs.scheduler import run_scheduler_tick

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings)
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


if __name__ == "__main__":
    asyncio.run(main())
