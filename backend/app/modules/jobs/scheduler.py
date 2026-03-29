"""Periodic scheduler tasks.

Runs on a 15-second interval. Handles:
  1. Republish pending jobs (Kafka retry)
  2. Clean up expired summary cache
  3. Sync dead jobs to dead-letter queue
  4. Clean up old failed jobs
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

        retryable_failed_jobs = await jobs_repo.list_retryable_failed_jobs(
            session,
            limit=100,
            backoff_seconds=settings.scheduler_failed_job_retry_backoff_seconds,
        )
        for job in retryable_failed_jobs:
            await jobs_repo.requeue_failed_job(job)

        published = await republish_pending_jobs(session, limit=100)
        dead_lettered_jobs = await jobs_repo.sync_dead_jobs_to_dead_letters(session, limit=200)

        cache_cutoff = datetime.now(UTC) - timedelta(days=settings.summary_cache_ttl_days)
        cleaned_summary_cache = await summary_repo.cleanup_expired(
            session, before=cache_cutoff,
        )

        cleaned_failed_jobs = await jobs_repo.cleanup_failed_jobs(
            session, retention_days=settings.scheduler_failed_job_retention_days,
        )
        cleaned_dead_letters = await jobs_repo.cleanup_dead_letters(
            session, retention_days=settings.scheduler_dead_letter_retention_days,
        )

        await session.commit()

        observe_scheduler_action(action="republished_jobs", count=published)
        observe_scheduler_action(action="requeued_failed_jobs", count=len(retryable_failed_jobs))
        observe_scheduler_action(action="dead_lettered_jobs", count=dead_lettered_jobs)
        observe_scheduler_action(action="cleaned_summary_cache", count=cleaned_summary_cache)
        observe_scheduler_action(action="cleaned_failed_jobs", count=cleaned_failed_jobs)
        observe_scheduler_action(action="cleaned_dead_letters", count=cleaned_dead_letters)

        return {
            "requeuedFailedJobs": len(retryable_failed_jobs),
            "republishedJobs": published,
            "deadLetteredJobs": dead_lettered_jobs,
            "cleanedSummaryCache": cleaned_summary_cache,
            "cleanedFailedJobs": cleaned_failed_jobs,
            "cleanedDeadLetters": cleaned_dead_letters,
        }
    return {
        "requeuedFailedJobs": 0,
        "republishedJobs": 0,
        "deadLetteredJobs": 0,
        "cleanedSummaryCache": 0,
        "cleanedFailedJobs": 0,
        "cleanedDeadLetters": 0,
    }
