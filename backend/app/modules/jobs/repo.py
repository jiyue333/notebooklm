from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job, JobDeadLetter


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


async def list_pending_publish_jobs(
    session: AsyncSession,
    *,
    limit: int = 100,
    publish_timeout_seconds: int = 120,
) -> list[Job]:
    now = datetime.now(UTC)
    stale_cutoff = now - timedelta(seconds=publish_timeout_seconds)
    result = await session.execute(
        select(Job)
        .where(
            or_(
                (Job.status == "pending_publish") & (Job.available_at <= now),
                (Job.status == "publishing") & (Job.available_at <= stale_cutoff),
            )
        )
        .order_by(Job.created_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def mark_job_publishing(job: Job) -> None:
    job.status = "publishing"
    job.available_at = datetime.now(UTC)


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


async def mark_job_failed(
    job: Job,
    *,
    error: str,
    session: AsyncSession | None = None,
    retryable: bool = True,
    error_code: str | None = None,
) -> None:
    if retryable and job.attempts < job.max_attempts:
        job.status = "failed"
    else:
        job.status = "dead"
        if not retryable:
            job.attempts = max(job.attempts, job.max_attempts)
    job.finished_at = datetime.now(UTC)
    job.last_error = error[:4000]
    if job.status == "dead" and session is not None:
        await _upsert_dead_letter(
            session,
            job=job,
            dead_reason="non_retryable" if not retryable else "attempts_exhausted",
            error_code=error_code,
        )


async def list_retryable_failed_jobs(
    session: AsyncSession,
    *,
    limit: int = 100,
    backoff_seconds: int = 30,
) -> list[Job]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=backoff_seconds)
    result = await session.execute(
        select(Job)
        .where(
            Job.status == "failed",
            Job.attempts < Job.max_attempts,
            Job.finished_at.is_not(None),
            Job.finished_at <= cutoff,
        )
        .order_by(Job.finished_at.asc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def requeue_failed_job(job: Job) -> None:
    job.status = "pending_publish"
    job.available_at = datetime.now(UTC)
    job.started_at = None
    job.finished_at = None


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


async def sync_dead_jobs_to_dead_letters(session: AsyncSession, *, limit: int = 100) -> int:
    result = await session.execute(
        select(Job)
        .where(
            Job.status == "dead",
            ~select(JobDeadLetter.id).where(JobDeadLetter.job_id == Job.id).exists(),
        )
        .order_by(Job.finished_at.asc().nulls_last(), Job.created_at.asc())
        .limit(limit)
    )
    dead_jobs = list(result.scalars().all())
    for job in dead_jobs:
        await _upsert_dead_letter(
            session,
            job=job,
            dead_reason="attempts_exhausted",
            error_code=None,
        )
    return len(dead_jobs)


async def mark_dead_letter_replayed_for_article(
    session: AsyncSession,
    *,
    article_id: str,
    replay_job_id: str,
) -> None:
    result = await session.execute(
        select(JobDeadLetter)
        .where(JobDeadLetter.article_id == article_id)
        .order_by(JobDeadLetter.dead_at.desc())
        .limit(1)
    )
    dead_letter = result.scalar_one_or_none()
    if dead_letter is None:
        return
    dead_letter.replay_count += 1
    dead_letter.last_replay_job_id = replay_job_id
    dead_letter.replayed_at = datetime.now(UTC)


async def cleanup_dead_letters(session: AsyncSession, *, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        select(JobDeadLetter.id).where(JobDeadLetter.dead_at < cutoff)
    )
    dead_letter_ids = list(result.scalars().all())
    if not dead_letter_ids:
        return 0
    await session.execute(delete(JobDeadLetter).where(JobDeadLetter.id.in_(dead_letter_ids)))
    return len(dead_letter_ids)


async def _upsert_dead_letter(
    session: AsyncSession,
    *,
    job: Job,
    dead_reason: str,
    error_code: str | None,
) -> JobDeadLetter:
    result = await session.execute(
        select(JobDeadLetter).where(JobDeadLetter.job_id == job.id).limit(1)
    )
    existing = result.scalar_one_or_none()
    dead_at = job.finished_at or datetime.now(UTC)
    if existing is not None:
        existing.last_error = (job.last_error or "")[:4000] or None
        existing.error_code = error_code
        existing.dead_reason = dead_reason
        existing.attempts = job.attempts
        existing.max_attempts = job.max_attempts
        existing.payload_json = dict(job.payload_json or {})
        existing.dead_at = dead_at
        return existing

    dead_letter = JobDeadLetter(
        job_id=job.id,
        job_type=job.job_type,
        article_id=job.article_id,
        search_session_id=job.search_session_id,
        dedupe_key=job.dedupe_key,
        payload_json=dict(job.payload_json or {}),
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        last_error=(job.last_error or "")[:4000] or None,
        error_code=error_code,
        dead_reason=dead_reason,
        created_at=job.created_at,
        dead_at=dead_at,
    )
    session.add(dead_letter)
    await session.flush()
    return dead_letter
