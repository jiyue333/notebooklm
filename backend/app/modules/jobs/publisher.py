from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infra.mq.message import MQMessage
from app.infra.mq.producer import KafkaProducer
from app.infra.mq.topics import (
    TAG_ARTICLE_INGEST,
    TAG_ARTICLE_REINDEX,
    TAG_SEARCH_DEEP,
)
from app.modules.jobs import repo
from app.modules.jobs.local_runner import run_job_inline
from app.modules.jobs.models import Job

logger = structlog.get_logger(__name__)

JOB_TAG_MAP = {
    "article_ingest": TAG_ARTICLE_INGEST,
    "article_reindex": TAG_ARTICLE_REINDEX,
    "search_deep": TAG_SEARCH_DEEP,
}


def _build_message(job: Job) -> MQMessage:
    tag = JOB_TAG_MAP[job.job_type]
    body = {"jobId": job.id, **job.payload_json}
    return MQMessage(
        topic=get_settings().kafka_topic,
        tag=tag,
        body=body,
        keys=[job.id, job.dedupe_key],
    )


async def publish_jobs(session: AsyncSession, jobs: list[Job]) -> None:
    if not jobs:
        return

    producer = KafkaProducer(client_id="notebooklm-api")
    try:
        for job in jobs:
            await producer.publish(_build_message(job))
            await repo.mark_job_queued(job)
    except ImportError as exc:
        logger.warning("jobs.publish_unavailable", error=str(exc))
        for job in jobs:
            if job.status != "queued":
                try:
                    await run_job_inline(job.id, job_type=job.job_type)
                    await session.refresh(job)
                except Exception as inline_exc:
                    logger.exception(
                        "jobs.inline_fallback_failed",
                        job_id=job.id,
                        error=str(inline_exc),
                    )
                    await repo.mark_job_pending_publish(job, error=str(exc))
    except Exception as exc:
        logger.exception("jobs.publish_failed", error=str(exc))
        for job in jobs:
            if job.status != "queued":
                try:
                    await run_job_inline(job.id, job_type=job.job_type)
                    await session.refresh(job)
                except Exception as inline_exc:
                    logger.exception(
                        "jobs.inline_fallback_failed",
                        job_id=job.id,
                        error=str(inline_exc),
                    )
                    await repo.mark_job_pending_publish(job, error=str(exc))
    finally:
        await producer.shutdown()


async def republish_pending_jobs(session: AsyncSession, *, limit: int = 100) -> int:
    jobs = await repo.list_pending_publish_jobs(session, limit=limit)
    if not jobs:
        return 0
    await publish_jobs(session, jobs)
    return len(jobs)
