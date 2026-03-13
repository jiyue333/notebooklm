from __future__ import annotations

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_scheduler_action
from app.infra.db.session import get_session_manager
from app.modules.ai.summary import repo as summary_repo
from app.modules.jobs import repo as jobs_repo
from app.modules.jobs.publisher import republish_pending_jobs
from app.modules.search.sessions import repo as repo_search
from app.modules.tracker import run_periodic_redis_inspection


async def run_scheduler_tick() -> dict[str, int]:
    async for session in get_session_manager().session():
        settings = get_settings()
        published = await republish_pending_jobs(session, limit=100)
        expired_sessions = await repo_search.expire_stale_search_sessions(session)
        cleaned_summary_cache = await summary_repo.cleanup_expired_summary_cache(
            session,
            ttl_days=settings.summary_cache_ttl_days,
        )
        cleaned_failed_jobs = await jobs_repo.cleanup_failed_jobs(
            session,
            retention_days=settings.scheduler_failed_job_retention_days,
        )
        redis_inspection = await run_periodic_redis_inspection()
        await session.commit()
        observe_scheduler_action(action="republished_jobs", count=published)
        observe_scheduler_action(action="expired_search_sessions", count=expired_sessions)
        observe_scheduler_action(action="cleaned_summary_cache", count=cleaned_summary_cache)
        observe_scheduler_action(action="cleaned_failed_jobs", count=cleaned_failed_jobs)
        observe_scheduler_action(
            action="redis_bigkeys_detected",
            count=redis_inspection.bigkey_count if redis_inspection else 0,
        )
        observe_scheduler_action(
            action="redis_hotkeys_detected",
            count=redis_inspection.hotkey_count if redis_inspection else 0,
        )
        return {
            "republishedJobs": published,
            "expiredSearchSessions": expired_sessions,
            "cleanedSummaryCache": cleaned_summary_cache,
            "cleanedFailedJobs": cleaned_failed_jobs,
            "redisKeysScanned": redis_inspection.keys_scanned if redis_inspection else 0,
            "redisBigkeys": redis_inspection.bigkey_count if redis_inspection else 0,
            "redisHotkeys": redis_inspection.hotkey_count if redis_inspection else 0,
        }
    return {
        "republishedJobs": 0,
        "expiredSearchSessions": 0,
        "cleanedSummaryCache": 0,
        "cleanedFailedJobs": 0,
        "redisKeysScanned": 0,
        "redisBigkeys": 0,
        "redisHotkeys": 0,
    }
