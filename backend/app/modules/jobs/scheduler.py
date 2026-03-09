from __future__ import annotations

from app.infra.db.session import get_session_manager
from app.modules.jobs.publisher import republish_pending_jobs
from app.modules.search import repo_search


async def run_scheduler_tick() -> dict[str, int]:
    async for session in get_session_manager().session():
        published = await republish_pending_jobs(session, limit=100)
        expired_sessions = await repo_search.expire_stale_search_sessions(session)
        await session.commit()
        return {
            "republishedJobs": published,
            "expiredSearchSessions": expired_sessions,
        }
    return {
        "republishedJobs": 0,
        "expiredSearchSessions": 0,
    }
