"""摘要缓存持久化仓储。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.summary.models import SummaryCache


async def get_cached_summary(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str | None = None,
    model_name: str | None = None,
    output_language: str | None = None,
) -> SummaryCache | None:
    stmt = (
        select(SummaryCache)
        .where(
            SummaryCache.article_id == article_id,
            SummaryCache.content_hash == content_hash,
            SummaryCache.prompt_version == prompt_version,
        )
        .order_by(desc(SummaryCache.created_at))
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def list_cached_summaries_by_article_ids(
    session: AsyncSession,
    *,
    article_ids: list[str],
    prompt_version: str,
) -> list[SummaryCache]:
    if not article_ids:
        return []

    result = await session.execute(
        select(SummaryCache)
        .where(
            SummaryCache.article_id.in_(article_ids),
            SummaryCache.prompt_version == prompt_version,
        )
        .order_by(desc(SummaryCache.created_at))
    )
    return list(result.scalars().all())


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
    now = datetime.now(UTC)
    stmt = (
        insert(SummaryCache)
        .values(
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=prompt_version,
            model_provider=model_provider,
            model_name=model_name,
            output_language=output_language,
            summary_text=summary_text,
            created_at=now,
        )
        .on_conflict_do_update(
            index_elements=[
                SummaryCache.article_id,
                SummaryCache.content_hash,
                SummaryCache.prompt_version,
            ],
            set_={
                "model_provider": model_provider,
                "model_name": model_name,
                "output_language": output_language,
                "summary_text": summary_text,
                "created_at": now,
            },
        )
        .returning(SummaryCache.id)
    )
    result = await session.execute(stmt)
    entry_id = result.scalar_one()
    entry = await session.get(SummaryCache, entry_id)
    if entry is None:
        # Defensive fallback; should not happen with RETURNING id.
        raise RuntimeError("summary cache upsert succeeded but row not found")
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
