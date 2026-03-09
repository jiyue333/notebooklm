from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job


async def create_job(
    session: AsyncSession,
    *,
    job_type: str,
    article_id: str | None,
    search_session_id: str | None,
    dedupe_key: str,
    payload_json: dict,
    created_at: datetime,
) -> Job:
    job = Job(
        job_type=job_type,
        article_id=article_id,
        search_session_id=search_session_id,
        dedupe_key=dedupe_key,
        payload_json=payload_json,
        status="pending_publish",
        attempts=0,
        max_attempts=3,
        created_at=created_at,
        available_at=created_at,
    )
    session.add(job)
    await session.flush()
    return job


async def create_article_ingest_job(
    session: AsyncSession,
    *,
    article_id: str,
    search_session_id: str | None,
    dedupe_key: str,
    payload_json: dict,
    created_at: datetime,
) -> Job:
    return await create_job(
        session,
        job_type="article_ingest",
        article_id=article_id,
        search_session_id=search_session_id,
        dedupe_key=dedupe_key,
        payload_json=payload_json,
        created_at=created_at,
    )


async def create_search_deep_job(
    session: AsyncSession,
    *,
    search_session_id: str,
    dedupe_key: str,
    payload_json: dict,
    created_at: datetime,
) -> Job:
    return await create_job(
        session,
        job_type="search_deep",
        article_id=None,
        search_session_id=search_session_id,
        dedupe_key=dedupe_key,
        payload_json=payload_json,
        created_at=created_at,
    )


async def create_article_reindex_job(
    session: AsyncSession,
    *,
    article_id: str,
    search_session_id: str | None,
    dedupe_key: str,
    payload_json: dict,
    created_at: datetime,
) -> Job:
    return await create_job(
        session,
        job_type="article_reindex",
        article_id=article_id,
        search_session_id=search_session_id,
        dedupe_key=dedupe_key,
        payload_json=payload_json,
        created_at=created_at,
    )


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    result = await session.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def list_pending_publish_jobs(session: AsyncSession, *, limit: int = 100) -> list[Job]:
    result = await session.execute(
        select(Job)
        .where(Job.status == "pending_publish", Job.available_at <= datetime.now(UTC))
        .order_by(Job.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_job_queued(job: Job) -> None:
    job.status = "queued"
    job.last_error = None


async def mark_job_pending_publish(job: Job, *, error: str | None = None) -> None:
    job.status = "pending_publish"
    job.last_error = error[:4000] if error else None


async def mark_job_running(job: Job) -> None:
    job.status = "running"
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    job.last_error = None


async def mark_job_succeeded(job: Job) -> None:
    job.status = "succeeded"
    job.finished_at = datetime.now(UTC)
    job.last_error = None


async def mark_job_failed(job: Job, *, error: str) -> None:
    job.status = "failed" if job.attempts < job.max_attempts else "dead"
    job.finished_at = datetime.now(UTC)
    job.last_error = error[:4000]


async def cleanup_failed_jobs(session: AsyncSession, *, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        select(Job.id).where(
            Job.status.in_(["failed", "dead"]),
            Job.finished_at.is_not(None),
            Job.finished_at < cutoff,
        )
    )
    job_ids = list(result.scalars().all())
    if not job_ids:
        return 0
    await session.execute(delete(Job).where(Job.id.in_(job_ids)))
    return len(job_ids)
