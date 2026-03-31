from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.api.sse import build_sse_error_payload, encode_sse_event
from app.infra.db.session import get_db_session
from app.modules.agent.summary.service import (
    build_summary_user_snapshot,
    generate_transient_summary,
    normalize_summary_language,
)
from app.modules.feeds import service
from app.modules.feeds.schemas import (
    FeedCategoryCreateRequest,
    FeedCreateRequest,
    FeedDiscoverRequest,
    FeedEntriesStatusUpdateRequest,
)
from app.modules.settings.runtime import get_merged_user_settings

router = APIRouter(prefix="/feeds", tags=["feeds"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


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


@router.post("/{feed_id}/history/load")
async def load_feed_history_endpoint(
    feed_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items, meta = await service.load_feed_history(
        session,
        user=current_user,
        local_feed_id=feed_id,
    )
    return success_response(
        items=items,
        meta=meta,
        message="历史文章加载完成" if items else "没有更多历史文章",
    )


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


@router.post("/entries/{entry_id}/summary/stream")
async def stream_entry_summary_endpoint(
    entry_id: int,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        try:
            entry = await service.get_entry_for_import(session, user=current_user, entry_id=entry_id)
            if not isinstance(entry, dict):
                yield build_sse_error_payload(
                    AppError(404, "未找到对应 RSS 条目", code="feed_entry_not_found"),
                    fallback_message="RSS 条目不存在",
                    fallback_code="feed_entry_not_found",
                )
                return

            clean_markdown = service.build_entry_summary_markdown(entry)
            if not clean_markdown:
                yield build_sse_error_payload(
                    AppError(422, "RSS 条目正文为空", code="feed_entry_content_empty"),
                    fallback_message="正文为空，无法生成摘要",
                    fallback_code="feed_entry_content_empty",
                )
                return

            summary_user = build_summary_user_snapshot(current_user)
            merged_settings = get_merged_user_settings(summary_user)
            output_language = normalize_summary_language(merged_settings.get("outputLanguage"))
            token_queue: asyncio.Queue[str] = asyncio.Queue()

            async def _on_token(piece: str) -> None:
                if piece:
                    await token_queue.put(piece)

            streamed_len = 0
            async for summary_session in get_db_session():
                task = asyncio.create_task(generate_transient_summary(
                    summary_session,
                    title=str(entry.get("title") or "未命名文章"),
                    clean_markdown=clean_markdown,
                    language=output_language,
                    user=summary_user,
                    token_sink=_on_token,
                ))

                while True:
                    if task.done() and token_queue.empty():
                        break
                    try:
                        token = await asyncio.wait_for(token_queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    if not token:
                        continue
                    streamed_len += len(token)
                    yield encode_sse_event("token", {"text": token})

                result = await task
                break

            summary_text = str(result.get("summary_text") or "").strip()
            if not streamed_len and summary_text:
                yield encode_sse_event("token", {"text": summary_text})
            yield encode_sse_event("done", {
                "entryId": entry_id,
                "summaryText": summary_text,
                "cached": bool(result.get("cached")),
                "language": output_language,
            })
        except Exception as exc:
            yield build_sse_error_payload(
                exc,
                fallback_message="RSS 摘要生成失败",
                fallback_code="feed_entry_summary_failed",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.put("/entries/status")
async def update_entries_status_endpoint(
    payload: FeedEntriesStatusUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await service.update_entries_status(
        session,
        user=current_user,
        entry_ids=payload.entryIds,
        status=payload.status,
    )
    return success_response(message="状态已更新")


@router.put("/entries/{entry_id}/bookmark")
async def toggle_entry_bookmark_endpoint(
    entry_id: int,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await service.toggle_entry_bookmark(session, user=current_user, entry_id=entry_id)
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
