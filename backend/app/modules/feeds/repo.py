from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.feeds.models import RssFeed


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
