from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import html
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.modules.feeds import repo as feeds_repo
from app.modules.feeds.client import MinifluxClient, MinifluxClientError
from app.modules.feeds.models import RssFeed
from app.modules.settings.runtime import get_merged_user_settings

_STRIP_HTML_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(slots=True)
class MinifluxRuntimeConfig:
    base_url: str
    admin_api_token: str | None
    admin_username: str | None
    admin_password: str | None
    admin_auth_source: str
    rsshub_url: str
    digest_time: str
    digest_language: str | None
    managed_user_prefix: str

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.admin_auth_source != "missing")


def resolve_miniflux_runtime_config(user) -> MinifluxRuntimeConfig:
    settings = get_settings()
    merged = get_merged_user_settings(user)

    base_url = str(merged.get("minifluxUrl") or settings.miniflux_default_url or "").strip().rstrip("/")
    rsshub_url = str(merged.get("rsshubUrl") or settings.rsshub_default_url or "").strip().rstrip("/")
    digest_time = str(merged.get("digestTime") or "08:00").strip() or "08:00"
    digest_language = merged.get("digestLanguage")

    admin_api_token = str(settings.miniflux_default_api_token or "").strip() or None
    admin_username = str(settings.miniflux_admin_username or "").strip() or None
    admin_password = str(settings.miniflux_admin_password or "").strip() or None
    if admin_api_token:
        admin_auth_source = "api_token"
    elif admin_username and admin_password:
        admin_auth_source = "basic"
    else:
        admin_auth_source = "missing"

    return MinifluxRuntimeConfig(
        base_url=base_url,
        admin_api_token=admin_api_token,
        admin_username=admin_username,
        admin_password=admin_password,
        admin_auth_source=admin_auth_source,
        rsshub_url=rsshub_url,
        digest_time=digest_time,
        digest_language=digest_language,
        managed_user_prefix=str(settings.miniflux_managed_user_prefix or "nblm").strip() or "nblm",
    )


def ensure_miniflux_runtime(user) -> MinifluxRuntimeConfig:
    runtime = resolve_miniflux_runtime_config(user)
    if not runtime.base_url:
        raise AppError(422, "未配置 Miniflux 服务地址", code="miniflux_url_missing")
    if runtime.admin_auth_source == "missing":
        raise AppError(
            422,
            "未配置 Miniflux 管理员凭证（MINIFLUX_DEFAULT_API_TOKEN 或 MINIFLUX_ADMIN_USERNAME / MINIFLUX_ADMIN_PASSWORD）",
            code="miniflux_admin_auth_missing",
        )
    return runtime


def _build_managed_miniflux_username(*, user, runtime: MinifluxRuntimeConfig) -> str:
    user_suffix = re.sub(r"[^a-z0-9]", "", str(getattr(user, "id", "")).lower())[:32]
    if not user_suffix:
        user_suffix = "anonymous"
    instance_suffix = sha256(str(get_settings().secret_key).encode("utf-8")).hexdigest()[:8]
    prefix = re.sub(r"[^a-z0-9_]", "", runtime.managed_user_prefix.lower())[:16] or "nblm"
    return f"{prefix}_{instance_suffix}_{user_suffix}"


def _build_managed_miniflux_password(*, user) -> str:
    digest = sha256(f"{get_settings().secret_key}|{getattr(user, 'id', '')}|miniflux-user".encode("utf-8")).hexdigest()
    return f"NBLM-{digest[:24]}-{digest[24:48]}"


def _build_admin_client(runtime: MinifluxRuntimeConfig) -> MinifluxClient:
    if runtime.admin_api_token:
        return MinifluxClient(
            base_url=runtime.base_url,
            api_token=runtime.admin_api_token,
        )
    return MinifluxClient(
        base_url=runtime.base_url,
        username=runtime.admin_username,
        password=runtime.admin_password,
    )


async def _ensure_managed_remote_user(*, user, runtime: MinifluxRuntimeConfig) -> str:
    username = _build_managed_miniflux_username(user=user, runtime=runtime)
    password = _build_managed_miniflux_password(user=user)
    async with _build_admin_client(runtime) as admin_client:
        try:
            await admin_client.get_user(username)
        except MinifluxClientError as exc:
            if exc.status_code == 404:
                await admin_client.create_user(
                    username=username,
                    password=password,
                    is_admin=False,
                )
                return username
            raise

        await admin_client.update_user(
            username,
            password=password,
            is_admin=False,
        )
    return username


async def _run_user_client_operation(*, user, operation):
    runtime = ensure_miniflux_runtime(user)
    username = _build_managed_miniflux_username(user=user, runtime=runtime)
    password = _build_managed_miniflux_password(user=user)
    try:
        async with MinifluxClient(base_url=runtime.base_url, username=username, password=password) as client:
            return await operation(client)
    except MinifluxClientError as exc:
        if exc.status_code not in {401, 403, 404}:
            raise

    await _ensure_managed_remote_user(user=user, runtime=runtime)
    async with MinifluxClient(base_url=runtime.base_url, username=username, password=password) as client:
        return await operation(client)


def _normalize_status(status: str) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"read", "unread", "removed", "all"}:
        return normalized
    raise AppError(422, "status 必须是 read / unread / removed / all", code="invalid_entry_status")


def _strip_html(value: str | None) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    without_tags = _STRIP_HTML_RE.sub(" ", raw)
    unescaped = html.unescape(without_tags)
    return _WHITESPACE_RE.sub(" ", unescaped).strip()


def _build_preview(value: str | None, *, max_chars: int = 220) -> str:
    text = _strip_html(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}..."


def _build_ai_summary(preview: str) -> str:
    if not preview:
        return "暂无摘要"
    if len(preview) <= 90:
        return preview
    return f"{preview[:90].rstrip()}..."


def _to_entry_view(entry: dict[str, Any], *, local_feed_map: dict[int, RssFeed], include_content: bool = False) -> dict:
    raw_feed = entry.get("feed") or {}
    raw_feed_id = entry.get("feed_id") or raw_feed.get("id")
    try:
        miniflux_feed_id = int(raw_feed_id)
    except (TypeError, ValueError):
        miniflux_feed_id = 0

    local_feed = local_feed_map.get(miniflux_feed_id)
    feed_title = str(raw_feed.get("title") or local_feed.title if local_feed else raw_feed.get("title") or "")

    preview = _build_preview(entry.get("content") or entry.get("summary") or "")
    published_at = entry.get("published_at") or entry.get("created_at")

    item = {
        "entryId": int(entry.get("id") or 0),
        "feedId": local_feed.id if local_feed else None,
        "minifluxFeedId": miniflux_feed_id or None,
        "feedTitle": feed_title,
        "title": entry.get("title") or "未命名文章",
        "url": entry.get("url") or "",
        "author": entry.get("author") or "",
        "publishedAt": published_at,
        "readingTime": entry.get("reading_time") or entry.get("reading_time_minutes"),
        "status": entry.get("status") or "unread",
        "starred": bool(entry.get("starred")),
        "aiSummary": _build_ai_summary(preview),
        "contentPreview": preview,
        "hash": entry.get("hash"),
    }

    if include_content:
        item["contentHtml"] = entry.get("content") or ""
    return item


def _map_miniflux_error(exc: MinifluxClientError) -> AppError:
    if exc.status_code in {401, 403}:
        return AppError(422, "Miniflux 鉴权失败，请检查托管账号或管理员凭证", code="miniflux_auth_failed")
    if exc.status_code == 404:
        return AppError(404, "资源不存在或已被删除", code="miniflux_resource_not_found")
    if exc.status_code == 409:
        return AppError(409, exc.message or "Miniflux 发生冲突", code="miniflux_conflict")
    if exc.status_code >= 500:
        return AppError(503, "Miniflux 服务不可用", code="miniflux_unavailable")
    return AppError(502, exc.message or "Miniflux 请求失败", code="miniflux_request_failed")


async def _ensure_local_feed_from_remote(
    session: AsyncSession,
    *,
    user_id: str,
    remote_feed: dict[str, Any],
) -> RssFeed:
    category = remote_feed.get("category") or {}
    return await feeds_repo.upsert_feed(
        session,
        user_id=user_id,
        miniflux_feed_id=int(remote_feed.get("id")),
        title=str(remote_feed.get("title") or "未命名订阅源"),
        feed_url=str(remote_feed.get("feed_url") or ""),
        site_url=(remote_feed.get("site_url") or None),
        category_name=(category.get("title") or None),
        crawler_enabled=bool(remote_feed.get("crawler")),
        is_active=not bool(remote_feed.get("disabled")),
    )


def _build_feed_view(local_feed: RssFeed, remote_feed: dict[str, Any] | None = None, unread_count: int = 0) -> dict:
    remote = remote_feed or {}
    category = remote.get("category") or {}
    return {
        "id": local_feed.id,
        "minifluxFeedId": local_feed.miniflux_feed_id,
        "title": local_feed.title,
        "feedUrl": local_feed.feed_url,
        "siteUrl": local_feed.site_url,
        "categoryName": local_feed.category_name or category.get("title"),
        "iconData": local_feed.icon_data,
        "isActive": local_feed.is_active,
        "crawlerEnabled": local_feed.crawler_enabled,
        "unreadCount": int(unread_count),
        "checkedAt": remote.get("checked_at"),
    }


async def _list_remote_feeds_with_counters(client: MinifluxClient) -> tuple[list[dict], dict]:
    remote_feeds = await client.list_feeds()
    counters = await client.get_feed_counters()
    return remote_feeds, counters


async def _create_feed_and_fetch_counters(
    client: MinifluxClient,
    *,
    feed_url: str,
    category_name: str | None,
) -> tuple[dict, dict]:
    category_id: int | None = None
    if category_name:
        categories = await client.list_categories()
        matched = next(
            (
                category for category in categories
                if str(category.get("title") or "").strip().lower() == category_name.strip().lower()
            ),
            None,
        )
        if matched is None:
            created = await client.create_category(category_name.strip())
            category_id = int(created.get("id"))
        else:
            category_id = int(matched.get("id"))

    normalized_feed_url = feed_url
    try:
        discovered = await client.discover(feed_url)
        if discovered:
            first_url = str((discovered[0] or {}).get("url") or "").strip()
            if first_url:
                normalized_feed_url = first_url
    except MinifluxClientError:
        # 保持兼容：discover 失败时仍尝试直接订阅用户输入 URL
        normalized_feed_url = feed_url

    miniflux_feed_id = await client.create_feed(
        feed_url=normalized_feed_url,
        category_id=category_id,
        # 默认启用全文抓取，保证条目内容尽量完整。
        crawler=True,
    )
    remote_feed = await client.get_feed(miniflux_feed_id)
    counters = await client.get_feed_counters()
    return remote_feed, counters


async def _list_entries_and_counters(
    client: MinifluxClient,
    *,
    params: dict[str, Any],
    category_name: str | None,
    miniflux_feed_id: int | None,
) -> tuple[dict, dict]:
    query_params = dict(params)
    if category_name:
        categories = await client.list_categories()
        category = next(
            (
                item for item in categories
                if str(item.get("title") or "").strip().lower() == category_name.strip().lower()
            ),
            None,
        )
        if category is None:
            return {"entries": [], "total": 0}, {"reads": {}, "unreads": {}}
        query_params["category_id"] = int(category.get("id"))

    if miniflux_feed_id is not None:
        payload = await client.list_feed_entries(miniflux_feed_id, params=query_params)
    else:
        payload = await client.list_entries(params=query_params)
    counters = await client.get_feed_counters()
    return payload, counters


async def _get_me_and_version(client: MinifluxClient) -> tuple[dict, dict]:
    me = await client.get_me()
    version = await client.get_version()
    return me, version


async def discover_feeds(user, *, url: str) -> list[dict]:
    try:
        discovered = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.discover(url),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    return [
        {
            "url": item.get("url"),
            "title": item.get("title") or "未命名订阅",
            "type": item.get("type") or "rss",
        }
        for item in discovered
    ]


async def list_feeds(session: AsyncSession, *, user) -> tuple[list[dict], dict]:
    try:
        remote_feeds, counters = await _run_user_client_operation(
            user=user,
            operation=_list_remote_feeds_with_counters,
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    local_feeds = await feeds_repo.list_user_feeds(session, user_id=user.id)
    local_by_miniflux = {feed.miniflux_feed_id: feed for feed in local_feeds}
    remote_ids: set[int] = set()

    for remote in remote_feeds:
        remote_id = int(remote.get("id"))
        remote_ids.add(remote_id)
        local_feed = local_by_miniflux.get(remote_id)
        if local_feed is None:
            local_feed = await _ensure_local_feed_from_remote(
                session,
                user_id=user.id,
                remote_feed=remote,
            )
            local_by_miniflux[remote_id] = local_feed
        else:
            updated = await _ensure_local_feed_from_remote(
                session,
                user_id=user.id,
                remote_feed=remote,
            )
            local_by_miniflux[remote_id] = updated

    for local in local_feeds:
        if local.miniflux_feed_id not in remote_ids:
            local.is_active = False

    await session.commit()

    unread_map = counters.get("unreads") or {}
    items = [
        _build_feed_view(
            local_by_miniflux[int(remote.get("id"))],
            remote_feed=remote,
            unread_count=int(unread_map.get(str(remote.get("id")), 0)),
        )
        for remote in remote_feeds
        if int(remote.get("id")) in local_by_miniflux
    ]

    total_unread = sum(int(value) for value in unread_map.values())
    return items, {
        "total": len(items),
        "unread": total_unread,
    }


async def create_feed(
    session: AsyncSession,
    *,
    user,
    feed_url: str,
    category_name: str | None,
) -> dict:
    try:
        remote_feed, counters = await _run_user_client_operation(
            user=user,
            operation=lambda client: _create_feed_and_fetch_counters(
                client,
                feed_url=feed_url,
                category_name=category_name,
            ),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    local_feed = await _ensure_local_feed_from_remote(
        session,
        user_id=user.id,
        remote_feed=remote_feed,
    )
    await session.commit()

    unread_count = int((counters.get("unreads") or {}).get(str(local_feed.miniflux_feed_id), 0))
    return _build_feed_view(local_feed, remote_feed=remote_feed, unread_count=unread_count)


async def remove_feed(session: AsyncSession, *, user, local_feed_id: str) -> None:
    feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=local_feed_id)
    if feed is None:
        raise AppError(404, "未找到对应订阅源", code="feed_not_found")

    try:
        await _run_user_client_operation(
            user=user,
            operation=lambda client: client.delete_feed(feed.miniflux_feed_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    await feeds_repo.delete_feed(session, feed)
    await session.commit()


async def refresh_feed(session: AsyncSession, *, user, local_feed_id: str) -> None:
    feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=local_feed_id)
    if feed is None:
        raise AppError(404, "未找到对应订阅源", code="feed_not_found")

    try:
        await _run_user_client_operation(
            user=user,
            operation=lambda client: client.refresh_feed(feed.miniflux_feed_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def list_categories(*, user) -> list[dict]:
    try:
        items = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.list_categories(),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    return [
        {
            "id": int(item.get("id")),
            "title": item.get("title") or "",
            "hideGlobally": bool(item.get("hide_globally")),
        }
        for item in items
    ]


async def create_category(*, user, title: str, hide_globally: bool = False) -> dict:
    try:
        item = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.create_category(title.strip(), hide_globally=hide_globally),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    return {
        "id": int(item.get("id")),
        "title": item.get("title") or title.strip(),
        "hideGlobally": bool(item.get("hide_globally")),
    }


async def delete_category(*, user, category_id: int) -> None:
    try:
        await _run_user_client_operation(
            user=user,
            operation=lambda client: client.delete_category(category_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def _build_local_feed_map(session: AsyncSession, *, user_id: str) -> dict[int, RssFeed]:
    local_feeds = await feeds_repo.list_user_feeds(session, user_id=user_id)
    return {feed.miniflux_feed_id: feed for feed in local_feeds}


async def list_entries(
    session: AsyncSession,
    *,
    user,
    status: str = "unread",
    limit: int = 100,
    offset: int = 0,
    category_name: str | None = None,
    search: str | None = None,
    local_feed_id: str | None = None,
) -> tuple[list[dict], dict]:
    status_value = _normalize_status(status)
    params: dict[str, Any] = {
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
        "direction": "desc",
        "order": "published_at",
    }
    if status_value != "all":
        params["status"] = status_value
    if search and search.strip():
        params["search"] = search.strip()

    local_feed: RssFeed | None = None
    if local_feed_id:
        local_feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=local_feed_id)
        if local_feed is None:
            raise AppError(404, "未找到对应订阅源", code="feed_not_found")

    try:
        payload, counters = await _run_user_client_operation(
            user=user,
            operation=lambda client: _list_entries_and_counters(
                client,
                params=params,
                category_name=category_name,
                miniflux_feed_id=local_feed.miniflux_feed_id if local_feed is not None else None,
            ),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    entries = payload.get("entries") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []

    local_feed_map = await _build_local_feed_map(session, user_id=user.id)
    items = [_to_entry_view(entry, local_feed_map=local_feed_map) for entry in entries]

    total = int(payload.get("total") or len(items)) if isinstance(payload, dict) else len(items)
    unread = sum(int(value) for value in (counters.get("unreads") or {}).values())
    return items, {
        "total": total,
        "unread": unread,
    }


async def get_entry(
    session: AsyncSession,
    *,
    user,
    entry_id: int,
) -> dict:
    try:
        entry = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.get_entry(entry_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    local_feed_map = await _build_local_feed_map(session, user_id=user.id)
    return _to_entry_view(entry, local_feed_map=local_feed_map, include_content=True)


async def update_entries_status(*, user, entry_ids: list[int], status: str) -> None:
    status_value = _normalize_status(status)

    try:
        await _run_user_client_operation(
            user=user,
            operation=lambda client: client.update_entries_status(entry_ids=entry_ids, status=status_value),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def toggle_entry_bookmark(*, user, entry_id: int) -> None:
    try:
        await _run_user_client_operation(
            user=user,
            operation=lambda client: client.toggle_bookmark(entry_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def get_digest(
    session: AsyncSession,
    *,
    user,
    target_date: date,
) -> dict:
    start_of_day = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)

    try:
        payload = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.list_entries(
                params={
                    "published_after": int(start_of_day.timestamp()),
                    "limit": 100,
                    "direction": "desc",
                    "order": "published_at",
                }
            ),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    entries = payload.get("entries") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []
    local_feed_map = await _build_local_feed_map(session, user_id=user.id)
    items = [_to_entry_view(entry, local_feed_map=local_feed_map) for entry in entries]

    return {
        "date": target_date.isoformat(),
        "entryCount": len(items),
        "summaryText": "",
        "entries": items,
        "status": "ready",
    }


async def test_connection(*, user) -> dict:
    runtime = ensure_miniflux_runtime(user)
    try:
        me, version = await _run_user_client_operation(
            user=user,
            operation=lambda client: _get_me_and_version(client),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    return {
        "ok": True,
        "baseUrl": runtime.base_url,
        "username": me.get("username") if isinstance(me, dict) else None,
        "version": version.get("version") if isinstance(version, dict) else None,
        "keySource": "managed_user",
        "managedUsername": _build_managed_miniflux_username(user=user, runtime=runtime),
    }


async def get_entry_for_import(*, user, entry_id: int) -> dict:
    try:
        return await _run_user_client_operation(
            user=user,
            operation=lambda client: client.get_entry(entry_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def mark_entries_as_read(*, user, entry_ids: list[int]) -> None:
    await update_entries_status(user=user, entry_ids=entry_ids, status="read")


async def ensure_local_feed_by_miniflux_id(
    session: AsyncSession,
    *,
    user,
    miniflux_feed_id: int,
) -> RssFeed | None:
    existing = await feeds_repo.get_feed_by_miniflux_id(
        session,
        user_id=user.id,
        miniflux_feed_id=miniflux_feed_id,
    )
    if existing is not None:
        return existing

    try:
        remote_feed = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.get_feed(miniflux_feed_id),
        )
    except MinifluxClientError as exc:
        if exc.status_code == 404:
            return None
        raise _map_miniflux_error(exc) from exc

    return await _ensure_local_feed_from_remote(session, user_id=user.id, remote_feed=remote_feed)
