"""摘要缓存持久化仓储。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.summary.models import (
    SummaryCache,
    SummaryCompressionCache,
    SummaryGenerationAudit,
)


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
    predicates = [
        SummaryCache.article_id == article_id,
        SummaryCache.content_hash == content_hash,
        SummaryCache.prompt_version == prompt_version,
    ]
    if model_provider:
        predicates.append(SummaryCache.model_provider == model_provider)
    if model_name:
        predicates.append(SummaryCache.model_name == model_name)
    if output_language:
        predicates.append(SummaryCache.output_language == output_language)
    stmt = select(SummaryCache).where(*predicates).order_by(desc(SummaryCache.created_at))
    result = await session.execute(stmt)
    return result.scalars().first()


async def get_latest_cached_summary(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
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
            constraint="uq_summary_caches_runtime_identity",
            set_={
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


async def get_compression_cache(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    article_type: str,
    compress_version: str,
    compress_code_blocks: bool,
) -> SummaryCompressionCache | None:
    stmt = (
        select(SummaryCompressionCache)
        .where(
            SummaryCompressionCache.article_id == article_id,
            SummaryCompressionCache.content_hash == content_hash,
            SummaryCompressionCache.prompt_version == prompt_version,
            SummaryCompressionCache.article_type == article_type,
            SummaryCompressionCache.compress_version == compress_version,
            SummaryCompressionCache.compress_code_blocks.is_(compress_code_blocks),
        )
        .order_by(desc(SummaryCompressionCache.created_at))
    )
    result = await session.execute(stmt)
    return result.scalars().first()


async def save_compression_cache(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    article_type: str,
    compress_version: str,
    compress_code_blocks: bool,
    compressed_content: str,
    original_length: int,
    compressed_length: int,
) -> SummaryCompressionCache:
    now = datetime.now(UTC)
    stmt = (
        insert(SummaryCompressionCache)
        .values(
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=prompt_version,
            article_type=article_type,
            compress_version=compress_version,
            compress_code_blocks=compress_code_blocks,
            compressed_content=compressed_content,
            original_length=original_length,
            compressed_length=compressed_length,
            created_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_summary_compression_identity",
            set_={
                "compressed_content": compressed_content,
                "original_length": original_length,
                "compressed_length": compressed_length,
                "created_at": now,
            },
        )
        .returning(SummaryCompressionCache.id)
    )
    result = await session.execute(stmt)
    entry_id = result.scalar_one()
    entry = await session.get(SummaryCompressionCache, entry_id)
    if entry is None:
        raise RuntimeError("summary compression cache upsert succeeded but row not found")
    return entry


async def append_generation_audit(
    session: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    output_language: str,
    status: str,
    summary_strategy: str,
    article_type: str,
    validation_passed: bool,
    fallback_used: bool,
    fallback_reason: str,
    retry_count: int,
    summary_length: int,
    latency_ms: int,
    error_code: str | None,
    error_message: str | None,
) -> SummaryGenerationAudit:
    entry = SummaryGenerationAudit(
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=prompt_version,
        model_provider=model_provider,
        model_name=model_name,
        output_language=output_language,
        status=status,
        summary_strategy=summary_strategy,
        article_type=article_type,
        validation_passed=validation_passed,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason[:64],
        retry_count=max(0, retry_count),
        summary_length=max(0, summary_length),
        latency_ms=max(0, latency_ms),
        error_code=(error_code or "")[:64] or None,
        error_message=(error_message or "")[:4000] or None,
        created_at=datetime.now(UTC),
    )
    session.add(entry)
    await session.flush()
    return entry
