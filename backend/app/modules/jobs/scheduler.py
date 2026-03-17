"""Periodic scheduler tasks.

Runs on a 15-second interval. Handles:
  1. Republish pending jobs (Kafka retry)
  2. Clean up expired summary cache
  3. Clean up old failed jobs
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_scheduler_action
from app.infra.db.session import get_session_manager
from app.modules.agent.summary import repo as summary_repo
from app.modules.jobs import repo as jobs_repo
from app.modules.jobs.publisher import republish_pending_jobs


async def run_scheduler_tick() -> dict[str, int]:
    async for session in get_session_manager().session():
        settings = get_settings()

        published = await republish_pending_jobs(session, limit=100)

        cache_cutoff = datetime.now(UTC) - timedelta(days=settings.summary_cache_ttl_days)
        cleaned_summary_cache = await summary_repo.cleanup_expired(
            session, before=cache_cutoff,
        )

        cleaned_failed_jobs = await jobs_repo.cleanup_failed_jobs(
            session, retention_days=settings.scheduler_failed_job_retention_days,
        )

        await session.commit()

        observe_scheduler_action(action="republished_jobs", count=published)
        observe_scheduler_action(action="cleaned_summary_cache", count=cleaned_summary_cache)
        observe_scheduler_action(action="cleaned_failed_jobs", count=cleaned_failed_jobs)

        return {
            "republishedJobs": published,
            "cleanedSummaryCache": cleaned_summary_cache,
            "cleanedFailedJobs": cleaned_failed_jobs,
        }
    return {
        "republishedJobs": 0,
        "cleanedSummaryCache": 0,
        "cleanedFailedJobs": 0,
    }
