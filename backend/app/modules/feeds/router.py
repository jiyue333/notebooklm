from __future__ import annotations

from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.feeds import service
from app.modules.feeds.schemas import (
    FeedCategoryCreateRequest,
    FeedCreateRequest,
    FeedDiscoverRequest,
    FeedEntriesStatusUpdateRequest,
)

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("/health")
async def feeds_health_endpoint(
    current_user=Depends(current_user_dep),
):
    item = await service.test_connection(user=current_user)
    return success_response(item=item)


@router.post("/discover")
async def discover_feeds_endpoint(
    payload: FeedDiscoverRequest,
    current_user=Depends(current_user_dep),
):
    items = await service.discover_feeds(current_user, url=payload.url.strip())
    return success_response(items=items)


@router.get("")
async def list_feeds_endpoint(
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items, meta = await service.list_feeds(session, user=current_user)
    return success_response(items=items, meta=meta)


@router.post("")
async def create_feed_endpoint(
    payload: FeedCreateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await service.create_feed(
        session,
        user=current_user,
        feed_url=payload.feedUrl.strip(),
        category_name=payload.categoryName.strip() if payload.categoryName else None,
    )
    return success_response(item=item)


@router.delete("/{feed_id}")
async def remove_feed_endpoint(
    feed_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await service.remove_feed(session, user=current_user, local_feed_id=feed_id)
    return success_response(message="订阅源已移除")


@router.put("/{feed_id}/refresh")
async def refresh_feed_endpoint(
    feed_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await service.refresh_feed(session, user=current_user, local_feed_id=feed_id)
    return success_response(message="刷新任务已触发")


@router.get("/categories")
async def list_categories_endpoint(
    current_user=Depends(current_user_dep),
):
    items = await service.list_categories(user=current_user)
    return success_response(items=items)


@router.post("/categories")
async def create_category_endpoint(
    payload: FeedCategoryCreateRequest,
    current_user=Depends(current_user_dep),
):
    item = await service.create_category(
        user=current_user,
        title=payload.title,
        hide_globally=bool(payload.hideGlobally),
    )
    return success_response(item=item)


@router.delete("/categories/{category_id}")
async def delete_category_endpoint(
    category_id: int,
    current_user=Depends(current_user_dep),
):
    await service.delete_category(user=current_user, category_id=category_id)
    return success_response(message="分类已删除")


@router.get("/entries")
async def list_entries_endpoint(
    status: str = Query(default="unread"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    categoryName: str | None = Query(default=None),
    search: str | None = Query(default=None),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items, meta = await service.list_entries(
        session,
        user=current_user,
        status=status,
        limit=limit,
        offset=offset,
        category_name=categoryName,
        search=search,
    )
    return success_response(items=items, meta=meta)


@router.get("/{feed_id}/entries")
async def list_feed_entries_endpoint(
    feed_id: str,
    status: str = Query(default="unread"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items, meta = await service.list_entries(
        session,
        user=current_user,
        status=status,
        limit=limit,
        offset=offset,
        search=search,
        local_feed_id=feed_id,
    )
    return success_response(items=items, meta=meta)


@router.get("/entries/{entry_id}")
async def get_entry_endpoint(
    entry_id: int,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await service.get_entry(
        session,
        user=current_user,
        entry_id=entry_id,
    )
    return success_response(item=item)


@router.put("/entries/status")
async def update_entries_status_endpoint(
    payload: FeedEntriesStatusUpdateRequest,
    current_user=Depends(current_user_dep),
):
    await service.update_entries_status(
        user=current_user,
        entry_ids=payload.entryIds,
        status=payload.status,
    )
    return success_response(message="状态已更新")


@router.put("/entries/{entry_id}/bookmark")
async def toggle_entry_bookmark_endpoint(
    entry_id: int,
    current_user=Depends(current_user_dep),
):
    await service.toggle_entry_bookmark(user=current_user, entry_id=entry_id)
    return success_response(message="星标状态已切换")


@router.get("/digest")
async def get_today_digest_endpoint(
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await service.get_digest(
        session,
        user=current_user,
        target_date=datetime.now(UTC).date(),
    )
    return success_response(item=item)


@router.get("/digest/{digest_date}")
async def get_digest_by_date_endpoint(
    digest_date: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    parsed_date = date.fromisoformat(digest_date)
    item = await service.get_digest(
        session,
        user=current_user,
        target_date=parsed_date,
    )
    return success_response(item=item)
