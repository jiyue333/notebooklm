from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.jobs.models import Job


async def create_article_ingest_job(
    session: AsyncSession,
    *,
    article_id: str,
    search_session_id: str | None,
    dedupe_key: str,
    payload_json: dict,
    created_at: datetime,
) -> Job:
    job = Job(
        job_type="article_ingest",
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
