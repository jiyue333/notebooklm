"""摘要缓存持久化仓储。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.summary.models import SummaryCache


async def get_cached_summary(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
) -> SummaryCache | None:
    result = await session.execute(
        select(SummaryCache).where(
            SummaryCache.article_id == article_id,
            SummaryCache.content_hash == content_hash,
            SummaryCache.prompt_version == prompt_version,
        )
    )
    return result.scalar_one_or_none()


async def save_summary_cache(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    output_language: str,
    summary_text: str,
) -> SummaryCache:
    entry = SummaryCache(
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=prompt_version,
        model_provider=model_provider,
        model_name=model_name,
        output_language=output_language,
        summary_text=summary_text,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.flush()
    return entry


async def cleanup_expired(
    session: AsyncSession,
    *,
    before: datetime,
) -> int:
    result = await session.execute(
        select(SummaryCache).where(SummaryCache.created_at < before)
    )
    rows = list(result.scalars().all())
    for row in rows:
        await session.delete(row)
    await session.flush()
    return len(rows)
