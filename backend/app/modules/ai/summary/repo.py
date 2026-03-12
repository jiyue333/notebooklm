from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.summary.models import SummaryCache


async def get_summary_cache(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    output_language: str,
) -> SummaryCache | None:
    result = await session.execute(
        select(SummaryCache).where(
            SummaryCache.article_id == article_id,
            SummaryCache.content_hash == content_hash,
            SummaryCache.prompt_version == prompt_version,
            SummaryCache.model_provider == model_provider,
            SummaryCache.model_name == model_name,
            SummaryCache.output_language == output_language,
        )
    )
    return result.scalar_one_or_none()


async def create_summary_cache(session: AsyncSession, cache: SummaryCache) -> SummaryCache:
    session.add(cache)
    await session.flush()
    return cache


async def cleanup_expired_summary_cache(
    session: AsyncSession,
    *,
    ttl_days: int,
) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
    result = await session.execute(
        select(SummaryCache.id).where(SummaryCache.updated_at < cutoff)
    )
    cache_ids = list(result.scalars().all())
    if not cache_ids:
        return 0
    await session.execute(delete(SummaryCache).where(SummaryCache.id.in_(cache_ids)))
    return len(cache_ids)

