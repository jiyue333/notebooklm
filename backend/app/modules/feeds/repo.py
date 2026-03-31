from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.feeds.models import RssFeed, RssHistoryEntry


async def list_user_feeds(session: AsyncSession, *, user_id: str) -> list[RssFeed]:
    result = await session.execute(
        select(RssFeed)
        .where(RssFeed.user_id == user_id)
        .order_by(RssFeed.updated_at.desc(), RssFeed.created_at.desc())
    )
    return list(result.scalars().all())


async def get_feed_by_local_id(
    session: AsyncSession,
    *,
    user_id: str,
    feed_id: str,
) -> RssFeed | None:
    result = await session.execute(
        select(RssFeed).where(
            RssFeed.user_id == user_id,
            RssFeed.id == feed_id,
        )
    )
    return result.scalar_one_or_none()


async def get_feed_by_miniflux_id(
    session: AsyncSession,
    *,
    user_id: str,
    miniflux_feed_id: int,
) -> RssFeed | None:
    result = await session.execute(
        select(RssFeed).where(
            RssFeed.user_id == user_id,
            RssFeed.miniflux_feed_id == miniflux_feed_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_feed(session: AsyncSession, feed: RssFeed) -> None:
    await session.delete(feed)


async def upsert_feed(
    session: AsyncSession,
    *,
    user_id: str,
    miniflux_feed_id: int,
    title: str,
    feed_url: str,
    site_url: str | None,
    category_name: str | None,
    crawler_enabled: bool,
    is_active: bool,
    icon_data: str | None = None,
) -> RssFeed:
    feed = await get_feed_by_miniflux_id(
        session,
        user_id=user_id,
        miniflux_feed_id=miniflux_feed_id,
    )
    if feed is None:
        feed = RssFeed(
            user_id=user_id,
            miniflux_feed_id=miniflux_feed_id,
            title=title,
            feed_url=feed_url,
            site_url=site_url,
            category_name=category_name,
            crawler_enabled=crawler_enabled,
            is_active=is_active,
            icon_data=icon_data,
        )
        session.add(feed)
    else:
        feed.title = title
        feed.feed_url = feed_url
        feed.site_url = site_url
        feed.category_name = category_name
        feed.crawler_enabled = crawler_enabled
        feed.is_active = is_active
        if icon_data is not None:
            feed.icon_data = icon_data

    await session.flush()
    return feed


async def list_history_entries(
    session: AsyncSession,
    *,
    user_id: str,
    feed_id: str | None = None,
    status: str = "all",
    search: str | None = None,
) -> list[RssHistoryEntry]:
    stmt = select(RssHistoryEntry).where(RssHistoryEntry.user_id == user_id)
    if feed_id:
        stmt = stmt.where(RssHistoryEntry.feed_id == feed_id)
    if status != "all":
        stmt = stmt.where(RssHistoryEntry.status == status)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                RssHistoryEntry.title.ilike(pattern),
                RssHistoryEntry.author.ilike(pattern),
                RssHistoryEntry.content_html.ilike(pattern),
                RssHistoryEntry.source_url.ilike(pattern),
            )
        )
    stmt = stmt.order_by(
        RssHistoryEntry.published_at.desc().nullslast(),
        RssHistoryEntry.created_at.desc(),
        RssHistoryEntry.id.desc(),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_history_entry(
    session: AsyncSession,
    *,
    user_id: str,
    history_entry_id: int,
) -> RssHistoryEntry | None:
    result = await session.execute(
        select(RssHistoryEntry).where(
            RssHistoryEntry.user_id == user_id,
            RssHistoryEntry.id == history_entry_id,
        )
    )
    return result.scalar_one_or_none()


async def get_history_entry_by_dedupe_key(
    session: AsyncSession,
    *,
    user_id: str,
    feed_id: str,
    dedupe_key: str,
) -> RssHistoryEntry | None:
    result = await session.execute(
        select(RssHistoryEntry).where(
            RssHistoryEntry.user_id == user_id,
            RssHistoryEntry.feed_id == feed_id,
            RssHistoryEntry.dedupe_key == dedupe_key,
        )
    )
    return result.scalar_one_or_none()


async def upsert_history_entry(
    session: AsyncSession,
    *,
    user_id: str,
    feed_id: str,
    dedupe_key: str,
    source_url: str | None,
    title: str,
    author: str | None,
    published_at,
    content_html: str | None,
    status: str = "unread",
    starred: bool = False,
) -> tuple[RssHistoryEntry, bool]:
    entry = await get_history_entry_by_dedupe_key(
        session,
        user_id=user_id,
        feed_id=feed_id,
        dedupe_key=dedupe_key,
    )
    created = entry is None
    if entry is None:
        entry = RssHistoryEntry(
            user_id=user_id,
            feed_id=feed_id,
            dedupe_key=dedupe_key,
            source_url=source_url,
            title=title,
            author=author,
            published_at=published_at,
            content_html=content_html,
            status=status,
            starred=starred,
        )
        session.add(entry)
    else:
        entry.source_url = source_url or entry.source_url
        entry.title = title or entry.title
        entry.author = author or entry.author
        entry.published_at = published_at or entry.published_at
        if content_html:
            entry.content_html = content_html
    await session.flush()
    return entry, created


async def count_history_unreads_by_feed_ids(
    session: AsyncSession,
    *,
    user_id: str,
    feed_ids: Sequence[str] | None = None,
) -> dict[str, int]:
    stmt = (
        select(RssHistoryEntry.feed_id, func.count(RssHistoryEntry.id))
        .where(
            RssHistoryEntry.user_id == user_id,
            RssHistoryEntry.status == "unread",
        )
        .group_by(RssHistoryEntry.feed_id)
    )
    if feed_ids:
        stmt = stmt.where(RssHistoryEntry.feed_id.in_(list(feed_ids)))
    result = await session.execute(stmt)
    return {feed_id: int(count or 0) for feed_id, count in result.all()}


async def count_total_history_unreads(
    session: AsyncSession,
    *,
    user_id: str,
) -> int:
    result = await session.execute(
        select(func.count(RssHistoryEntry.id)).where(
            RssHistoryEntry.user_id == user_id,
            RssHistoryEntry.status == "unread",
        )
    )
    return int(result.scalar() or 0)


async def update_history_entries_status(
    session: AsyncSession,
    *,
    user_id: str,
    history_entry_ids: Sequence[int],
    status: str,
) -> list[RssHistoryEntry]:
    if not history_entry_ids:
        return []
    result = await session.execute(
        select(RssHistoryEntry).where(
            RssHistoryEntry.user_id == user_id,
            RssHistoryEntry.id.in_(list(history_entry_ids)),
        )
    )
    items = list(result.scalars().all())
    for item in items:
        item.status = status
    await session.flush()
    return items


async def toggle_history_entry_bookmark(
    session: AsyncSession,
    *,
    user_id: str,
    history_entry_id: int,
) -> RssHistoryEntry | None:
    item = await get_history_entry(session, user_id=user_id, history_entry_id=history_entry_id)
    if item is None:
        return None
    item.starred = not item.starred
    await session.flush()
    return item
