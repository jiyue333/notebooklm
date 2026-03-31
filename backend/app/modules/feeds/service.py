from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import html
from html.parser import HTMLParser
import re
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.modules.feeds import repo as feeds_repo
from app.modules.feeds.client import MinifluxClient, MinifluxClientError
from app.modules.feeds.models import RssFeed, RssHistoryEntry
from app.modules.settings.runtime import get_merged_user_settings

_STRIP_HTML_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_ARTICLE_URL_PATH_RE = re.compile(r"/\d{4}/\d{2}/[^/?#]+(?:\.html?)?/?$", re.IGNORECASE)
_ABSOLUTE_URL_ATTR_RE = re.compile(r"""(?i)\b(href|src)=([\"'])([^\"']+)\2""")
_SUMMARY_HTML_BLOCK_REPLACEMENTS = (
    (r"(?i)<br\s*/?>", "\n"),
    (r"(?i)</p\s*>", "\n\n"),
    (r"(?i)</div\s*>", "\n\n"),
    (r"(?i)</section\s*>", "\n\n"),
    (r"(?i)</article\s*>", "\n\n"),
    (r"(?i)</li\s*>", "\n"),
    (r"(?is)<li[^>]*>", "- "),
)
_ENTRY_DATE_MIN = datetime(1970, 1, 1, tzinfo=UTC)
_HISTORY_BATCH_SIZE = 12
_HISTORY_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass(slots=True)
class _HistoryArticleCandidate:
    url: str
    title: str


@dataclass(slots=True)
class _ExtractedHistoryArticle:
    url: str
    title: str
    author: str | None
    published_at: datetime | None
    content_html: str


class _AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        href = attrs_map.get("href", "").strip()
        if href:
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None and data:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = html.unescape("".join(self._text_parts)).strip()
        self.links.append((self._href, _WHITESPACE_RE.sub(" ", text)))
        self._href = None
        self._text_parts = []


class _ContainerInnerHtmlParser(HTMLParser):
    def __init__(self, *, container_hints: tuple[str, ...]) -> None:
        super().__init__(convert_charrefs=False)
        self._container_hints = tuple(hint.lower() for hint in container_hints)
        self._capturing = False
        self._capture_tag: str | None = None
        self._nested_depth = 0
        self._parts: list[str] = []

    @property
    def html(self) -> str:
        return "".join(self._parts).strip()

    def _matches(self, tag: str, attrs: list[tuple[str, str | None]]) -> bool:
        tag_name = tag.lower()
        if any(hint == tag_name for hint in self._container_hints):
            return True
        attrs_map = {name.lower(): (value or "") for name, value in attrs}
        joined = f"{attrs_map.get('id', '')} {attrs_map.get('class', '')}".lower()
        return any(hint in joined for hint in self._container_hints)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._capturing:
            if self._matches(tag, attrs):
                self._capturing = True
                self._capture_tag = tag.lower()
                self._nested_depth = 0
            return
        self._parts.append(self.get_starttag_text())
        self._nested_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capturing:
            self._parts.append(self.get_starttag_text())

    def handle_data(self, data: str) -> None:
        if self._capturing and data:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capturing:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capturing:
            self._parts.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        tag_name = tag.lower()
        if self._nested_depth == 0 and tag_name == self._capture_tag:
            self._capturing = False
            self._capture_tag = None
            return
        self._parts.append(f"</{tag}>")
        if self._nested_depth > 0:
            self._nested_depth -= 1


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


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text

    preferred_boundaries = [
        text.rfind(symbol, 0, max_chars + 1)
        for symbol in ("。", "！", "？", ".", "!", "?", "；", ";", "，", ",")
    ]
    boundary = max(preferred_boundaries)
    if boundary >= int(max_chars * 0.58):
        return f"{text[:boundary + 1].rstrip()}..."
    return f"{text[:max_chars].rstrip()}..."


def _build_ai_summary(value: str | None, *, max_chars: int = 320) -> str:
    text = _strip_html(value)
    if not text:
        return "暂无摘要"
    return _truncate_text(text, max_chars=max_chars)


def _build_summary_text(value: str | None, *, max_chars: int = 1200) -> str:
    text = _strip_html(value)
    if not text:
        return ""
    return _truncate_text(text, max_chars=max_chars)


def _convert_html_to_markdown(value: str | None) -> str:
    raw = str(value or "")
    if not raw:
        return ""

    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    for pattern, replacement in _SUMMARY_HTML_BLOCK_REPLACEMENTS:
        stripped = re.sub(pattern, replacement, stripped)

    for level in range(6, 0, -1):
        stripped = re.sub(
            rf"(?is)<h{level}[^>]*>(.*?)</h{level}>",
            lambda match: f"\n\n{'#' * level} {_strip_html(match.group(1))}\n\n",
            stripped,
        )

    stripped = re.sub(r"(?is)<[^>]+>", " ", stripped)
    stripped = html.unescape(stripped)
    stripped = re.sub(r"\r\n?", "\n", stripped)
    stripped = re.sub(r"[ \t]+\n", "\n", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def build_entry_summary_markdown(entry: dict[str, Any]) -> str:
    title = str(entry.get("title") or "未命名文章").strip() or "未命名文章"
    source_url = str(entry.get("url") or "").strip()
    content_markdown = _convert_html_to_markdown(entry.get("content") or entry.get("summary") or "")
    if not content_markdown:
        fallback_text = _strip_html(entry.get("content") or entry.get("summary") or "")
        if fallback_text:
            content_markdown = fallback_text

    parts = [f"# {title}"]
    if source_url:
        parts.append(f"来源：{source_url}")
    if content_markdown:
        parts.append(content_markdown)
    return "\n\n".join(part for part in parts if part).strip()


def _is_history_entry_id(entry_id: int) -> bool:
    return int(entry_id) < 0


def _to_history_entry_id(history_entry_id: int) -> int:
    return -abs(int(history_entry_id))


def _from_history_entry_id(entry_id: int) -> int:
    return abs(int(entry_id))


def _parse_datetime_value(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _entry_sort_value(value: Any) -> datetime:
    return _parse_datetime_value(value) or _ENTRY_DATE_MIN


def _sort_entry_views(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _entry_sort_value(item.get("publishedAt")),
            int(item.get("entryId") or 0),
        ),
        reverse=True,
    )


def _build_history_entry_hash(*, source_url: str | None, title: str, published_at: datetime | None) -> str:
    seed = "|".join(
        [
            str(source_url or "").strip(),
            title.strip(),
            published_at.isoformat() if published_at else "",
        ]
    )
    return sha256(seed.encode("utf-8")).hexdigest()


def _to_history_raw_entry(entry: RssHistoryEntry, *, feed: RssFeed) -> dict[str, Any]:
    return {
        "id": _to_history_entry_id(entry.id),
        "feed_id": feed.miniflux_feed_id,
        "url": entry.source_url or "",
        "author": entry.author or "",
        "published_at": entry.published_at,
        "created_at": entry.created_at,
        "title": entry.title,
        "content": entry.content_html or "",
        "summary": entry.content_html or "",
        "status": entry.status,
        "starred": entry.starred,
        "hash": entry.dedupe_key,
        "feed": {
            "id": feed.miniflux_feed_id,
            "title": feed.title,
        },
    }


def _to_history_entry_view(entry: RssHistoryEntry, *, feed: RssFeed, include_content: bool = False) -> dict[str, Any]:
    raw_entry = _to_history_raw_entry(entry, feed=feed)
    item = _to_entry_view(raw_entry, local_feed_map={feed.miniflux_feed_id: feed}, include_content=include_content)
    item["entryId"] = _to_history_entry_id(entry.id)
    item["feedId"] = feed.id
    item["minifluxFeedId"] = feed.miniflux_feed_id
    item["feedTitle"] = feed.title
    item["status"] = entry.status
    item["starred"] = entry.starred
    item["hash"] = entry.dedupe_key
    return item


def _extract_first_match(patterns: tuple[str, ...], value: str) -> str:
    for pattern in patterns:
        match = re.search(pattern, value, re.IGNORECASE | re.DOTALL)
        if match:
            return html.unescape(_strip_html(match.group(1))).strip()
    return ""


def _extract_article_title(page_html: str) -> str:
    title = _extract_first_match(
        (
            r'<h1[^>]*>(.*?)</h1>',
            r'<h2[^>]*class="[^"]*entry-title[^"]*"[^>]*>(.*?)</h2>',
            r"<title>(.*?)</title>",
        ),
        page_html,
    )
    if " - " in title:
        title = title.split(" - ", 1)[0].strip()
    elif " | " in title:
        title = title.split(" | ", 1)[0].strip()
    return title


def _extract_article_author(page_html: str) -> str | None:
    author = _extract_first_match(
        (
            r'<meta[^>]+name="author"[^>]+content="([^"]+)"',
            r'<a[^>]+rel="author"[^>]*>(.*?)</a>',
            r'<span[^>]*class="[^"]*author[^"]*"[^>]*>(.*?)</span>',
        ),
        page_html,
    )
    return author or None


def _extract_article_published_at(page_html: str) -> datetime | None:
    patterns = (
        r'<abbr[^>]+class="[^"]*published[^"]*"[^>]+title="([^"]+)"',
        r'<time[^>]+datetime="([^"]+)"',
        r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
        r'<meta[^>]+name="pubdate"[^>]+content="([^"]+)"',
    )
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            parsed = _parse_datetime_value(match.group(1))
            if parsed is not None:
                return parsed
    return None


def _absolutize_urls_in_html(content_html: str, *, base_url: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        attr_name, quote, raw_value = match.groups()
        normalized = raw_value.strip()
        if not normalized or normalized.startswith(("data:", "javascript:", "mailto:", "#")):
            return match.group(0)
        absolute = urljoin(base_url, normalized)
        return f'{attr_name}={quote}{absolute}{quote}'

    return _ABSOLUTE_URL_ATTR_RE.sub(_replace, content_html)


def _normalize_history_url(url: str | None) -> str:
    normalized = str(url or "").strip()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _extract_article_content_html(page_html: str, *, article_url: str) -> str:
    for hints in (
        ("asset-content", "entry-content"),
        ("entry-content",),
        ("post-content",),
        ("article-content",),
        ("main-content",),
        ("entry-body",),
        ("post-body",),
        ("article",),
        ("main",),
    ):
        parser = _ContainerInnerHtmlParser(container_hints=hints)
        parser.feed(page_html)
        content_html = parser.html
        if len(_strip_html(content_html)) >= 80:
            return _absolutize_urls_in_html(content_html, base_url=article_url)
    return ""


def _looks_like_article_url(url: str, *, site_host: str | None = None) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if site_host and parsed.netloc and parsed.netloc != site_host:
        return False
    path = parsed.path or ""
    lowered = path.lower()
    if lowered.endswith((".xml", ".rss", ".atom", ".json", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".css", ".js")):
        return False
    if "archives" in lowered or lowered.endswith("/feed") or lowered.endswith("/feed/"):
        return False
    return bool(_ARTICLE_URL_PATH_RE.search(path))


def _month_archive_url_from_article_url(article_url: str | None) -> str | None:
    if not article_url:
        return None
    parsed = urlparse(article_url)
    match = re.search(r"(.*/\d{4}/\d{2})/[^/]+/?$", parsed.path)
    if not match:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, f"{match.group(1)}/", "", "", ""))


def _derive_site_root_url(feed: RssFeed) -> str | None:
    for candidate in (feed.site_url, feed.feed_url):
        normalized = str(candidate or "").strip()
        if not normalized:
            continue
        parsed = urlparse(normalized)
        if not parsed.scheme or not parsed.netloc:
            continue
        if normalized.endswith(".xml") or normalized.endswith(".rss") or normalized.endswith(".atom"):
            trimmed_path = parsed.path.rsplit("/", 1)[0] + "/"
            return urlunparse((parsed.scheme, parsed.netloc, trimmed_path, "", "", ""))
        return normalized if normalized.endswith("/") else f"{normalized}/"
    return None


def _extract_article_candidates(page_html: str, *, page_url: str) -> list[_HistoryArticleCandidate]:
    site_host = urlparse(page_url).netloc
    parser = _AnchorCollector()
    parser.feed(page_html)
    items: list[_HistoryArticleCandidate] = []
    seen: set[str] = set()
    for href, text in parser.links:
        absolute_url = _normalize_history_url(urljoin(page_url, href.strip()))
        if absolute_url in seen:
            continue
        if not _looks_like_article_url(absolute_url, site_host=site_host):
            continue
        seen.add(absolute_url)
        items.append(_HistoryArticleCandidate(url=absolute_url, title=text))
    return items


def _extract_prev_archive_url(page_html: str, *, page_url: str) -> str | None:
    for pattern in (
        r'<link[^>]+rel="prev"[^>]+href="([^"]+)"',
        r'<a[^>]+href="([^"]+)"[^>]*>\s*(?:&laquo;\s*)?上月\s*</a>',
    ):
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            return urljoin(page_url, match.group(1).strip())
    return None


async def _fetch_html_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        response = await client.get(url, headers=_HISTORY_HTTP_HEADERS)
    except httpx.HTTPError as exc:
        raise AppError(502, f"无法访问历史文章页面：{url}", code="feed_history_fetch_failed") from exc
    if response.status_code >= 400:
        raise AppError(502, f"历史文章页面返回异常：{response.status_code}", code="feed_history_fetch_failed")
    return response.text


async def _extract_history_article(
    client: httpx.AsyncClient,
    *,
    article_url: str,
    fallback_title: str = "",
) -> _ExtractedHistoryArticle | None:
    page_html = await _fetch_html_page(client, article_url)
    title = _extract_article_title(page_html) or fallback_title.strip()
    content_html = _extract_article_content_html(page_html, article_url=article_url)
    if not title or not content_html:
        return None
    return _ExtractedHistoryArticle(
        url=article_url,
        title=title,
        author=_extract_article_author(page_html),
        published_at=_extract_article_published_at(page_html),
        content_html=content_html,
    )


def _to_entry_view(entry: dict[str, Any], *, local_feed_map: dict[int, RssFeed], include_content: bool = False) -> dict:
    raw_feed = entry.get("feed") or {}
    raw_feed_id = entry.get("feed_id") or raw_feed.get("id")
    try:
        miniflux_feed_id = int(raw_feed_id)
    except (TypeError, ValueError):
        miniflux_feed_id = 0

    local_feed = local_feed_map.get(miniflux_feed_id)
    feed_title = str(raw_feed.get("title") or local_feed.title if local_feed else raw_feed.get("title") or "")

    summary_source = entry.get("content") or entry.get("summary") or ""
    preview = _build_preview(summary_source, max_chars=260)
    summary_text = _build_summary_text(summary_source, max_chars=1200)
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
        "aiSummary": _build_ai_summary(summary_source, max_chars=320),
        "contentPreview": preview,
        "summaryText": summary_text,
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


async def _build_merged_entry_payload(
    session: AsyncSession,
    *,
    user,
    payload: dict[str, Any],
    counters: dict[str, Any],
    local_feed_id: str | None,
    status_value: str,
    search: str | None,
) -> tuple[list[dict], dict]:
    entries = payload.get("entries") if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        entries = []

    local_feed_map = await _build_local_feed_map(session, user_id=user.id)
    remote_items = [_to_entry_view(entry, local_feed_map=local_feed_map) for entry in entries]

    history_items: list[dict] = []
    if local_feed_id:
        local_feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=local_feed_id)
        if local_feed is not None:
            history_entries = await feeds_repo.list_history_entries(
                session,
                user_id=user.id,
                feed_id=local_feed.id,
                status=status_value,
                search=search,
            )
            history_items = [_to_history_entry_view(item, feed=local_feed) for item in history_entries]
    elif status_value == "all" or (search and search.strip()):
        history_entries = await feeds_repo.list_history_entries(
            session,
            user_id=user.id,
            status=status_value,
            search=search,
        )
        feed_by_id = {feed.id: feed for feed in local_feed_map.values()}
        history_items = [
            _to_history_entry_view(item, feed=feed_by_id[item.feed_id])
            for item in history_entries
            if item.feed_id in feed_by_id
        ]

    combined_items = _sort_entry_views(remote_items + history_items)
    history_unread_total = await feeds_repo.count_total_history_unreads(session, user_id=user.id)
    unread_total = sum(int(value) for value in (counters.get("unreads") or {}).values()) + history_unread_total
    total = int(payload.get("total") or len(remote_items)) + len(history_items)
    return combined_items, {
        "total": total,
        "unread": unread_total,
    }


def _select_candidates_after_oldest(
    candidates: list[_HistoryArticleCandidate],
    *,
    oldest_known_url: str | None,
) -> list[_HistoryArticleCandidate]:
    if not oldest_known_url:
        return candidates
    for index, candidate in enumerate(candidates):
        if candidate.url == oldest_known_url:
            return candidates[index + 1:]
    return candidates


async def _discover_history_candidates(
    client: httpx.AsyncClient,
    *,
    feed: RssFeed,
    oldest_known_url: str | None,
) -> list[_HistoryArticleCandidate]:
    candidate_pages: list[str] = []
    month_page_url = _month_archive_url_from_article_url(oldest_known_url)
    if month_page_url:
        candidate_pages.append(month_page_url)
    site_root_url = _derive_site_root_url(feed)
    if site_root_url:
        candidate_pages.append(site_root_url)
        candidate_pages.append(urljoin(site_root_url, "archives.html"))

    discovered: list[_HistoryArticleCandidate] = []
    seen_pages: set[str] = set()
    seen_urls: set[str] = set()
    page_errors = 0

    while candidate_pages and len(discovered) < _HISTORY_BATCH_SIZE * 4:
        page_url = candidate_pages.pop(0)
        if not page_url or page_url in seen_pages:
            continue
        seen_pages.add(page_url)
        try:
            page_html = await _fetch_html_page(client, page_url)
        except AppError:
            page_errors += 1
            continue

        items = _extract_article_candidates(page_html, page_url=page_url)
        if page_url == month_page_url:
            prev_page = _extract_prev_archive_url(page_html, page_url=page_url)
            if prev_page and prev_page not in seen_pages:
                candidate_pages.insert(1, prev_page)
            items = _select_candidates_after_oldest(items, oldest_known_url=oldest_known_url)
        else:
            items = _select_candidates_after_oldest(items, oldest_known_url=oldest_known_url)

        for item in items:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            discovered.append(item)

    if not discovered and page_errors and len(seen_pages) == page_errors:
        raise AppError(502, "无法访问订阅源站点，无法拉取历史文章", code="feed_history_fetch_failed")
    return discovered


async def load_feed_history(
    session: AsyncSession,
    *,
    user,
    local_feed_id: str,
    batch_size: int = _HISTORY_BATCH_SIZE,
) -> tuple[list[dict], dict]:
    feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=local_feed_id)
    if feed is None:
        raise AppError(404, "未找到对应订阅源", code="feed_not_found")

    try:
        remote_payload, counters = await _run_user_client_operation(
            user=user,
            operation=lambda client: _list_entries_and_counters(
                client,
                params={
                    "limit": 240,
                    "offset": 0,
                    "direction": "desc",
                    "order": "published_at",
                },
                category_name=None,
                miniflux_feed_id=feed.miniflux_feed_id,
            ),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    remote_entries = remote_payload.get("entries") if isinstance(remote_payload, dict) else []
    if not isinstance(remote_entries, list):
        remote_entries = []

    history_entries = await feeds_repo.list_history_entries(
        session,
        user_id=user.id,
        feed_id=feed.id,
        status="all",
    )

    known_urls = {
        _normalize_history_url(entry.get("url"))
        for entry in remote_entries
        if _normalize_history_url(entry.get("url"))
    }
    known_urls.update(
        _normalize_history_url(item.source_url)
        for item in history_entries
        if _normalize_history_url(item.source_url)
    )

    known_records: list[tuple[datetime, str]] = []
    for entry in remote_entries:
        entry_url = _normalize_history_url(entry.get("url"))
        published_at = _parse_datetime_value(entry.get("published_at") or entry.get("created_at"))
        if entry_url and published_at:
            known_records.append((published_at, entry_url))
    for item in history_entries:
        if item.source_url and item.published_at:
            known_records.append((item.published_at, item.source_url))

    oldest_known_record = min(known_records, key=lambda item: item[0]) if known_records else None
    oldest_known_url = oldest_known_record[1] if oldest_known_record else None
    oldest_known_date = oldest_known_record[0] if oldest_known_record else None

    loaded_entries: list[RssHistoryEntry] = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20.0,
        trust_env=False,
        headers=_HISTORY_HTTP_HEADERS,
    ) as client:
        candidates = await _discover_history_candidates(
            client,
            feed=feed,
            oldest_known_url=oldest_known_url,
        )
        for candidate in candidates:
            if candidate.url in known_urls:
                continue
            try:
                extracted = await _extract_history_article(
                    client,
                    article_url=_normalize_history_url(candidate.url),
                    fallback_title=candidate.title,
                )
            except AppError:
                continue
            if extracted is None:
                continue
            if oldest_known_date and extracted.published_at and extracted.published_at >= oldest_known_date:
                continue

            dedupe_key = _build_history_entry_hash(
                source_url=_normalize_history_url(extracted.url),
                title=extracted.title,
                published_at=extracted.published_at,
            )
            persisted, created = await feeds_repo.upsert_history_entry(
                session,
                user_id=user.id,
                feed_id=feed.id,
                dedupe_key=dedupe_key,
                source_url=extracted.url,
                title=extracted.title,
                author=extracted.author,
                published_at=extracted.published_at,
                content_html=extracted.content_html,
                status="unread",
                starred=False,
            )
            if not created:
                continue
            loaded_entries.append(persisted)
            known_urls.add(extracted.url)
            if len(loaded_entries) >= batch_size:
                break

    await session.commit()

    loaded_items = _sort_entry_views([_to_history_entry_view(item, feed=feed) for item in loaded_entries])
    unread_total = sum(int(value) for value in (counters.get("unreads") or {}).values())
    unread_total += await feeds_repo.count_total_history_unreads(session, user_id=user.id)
    return loaded_items, {
        "loadedCount": len(loaded_items),
        "unread": unread_total,
    }


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
    local_history_unreads = await feeds_repo.count_history_unreads_by_feed_ids(
        session,
        user_id=user.id,
        feed_ids=[feed.id for feed in local_by_miniflux.values()],
    )
    items = [
        _build_feed_view(
            local_by_miniflux[int(remote.get("id"))],
            remote_feed=remote,
            unread_count=(
                int(unread_map.get(str(remote.get("id")), 0))
                + int(local_history_unreads.get(local_by_miniflux[int(remote.get("id"))].id, 0))
            ),
        )
        for remote in remote_feeds
        if int(remote.get("id")) in local_by_miniflux
    ]

    total_unread = sum(int(value) for value in unread_map.values()) + sum(local_history_unreads.values())
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
    remote_limit = max(1, min(max(limit + offset, limit), 400))
    params: dict[str, Any] = {
        "limit": remote_limit,
        "offset": 0,
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

    combined_items, meta = await _build_merged_entry_payload(
        session,
        user=user,
        payload=payload,
        counters=counters,
        local_feed_id=local_feed_id,
        status_value=status_value,
        search=search,
    )
    return combined_items[offset: offset + limit], meta


async def get_entry(
    session: AsyncSession,
    *,
    user,
    entry_id: int,
) -> dict:
    if _is_history_entry_id(entry_id):
        history_entry = await feeds_repo.get_history_entry(
            session,
            user_id=user.id,
            history_entry_id=_from_history_entry_id(entry_id),
        )
        if history_entry is None:
            raise AppError(404, "未找到对应 RSS 条目", code="feed_entry_not_found")
        feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=history_entry.feed_id)
        if feed is None:
            raise AppError(404, "未找到对应订阅源", code="feed_not_found")
        return _to_history_entry_view(history_entry, feed=feed, include_content=True)

    try:
        entry = await _run_user_client_operation(
            user=user,
            operation=lambda client: client.get_entry(entry_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc

    local_feed_map = await _build_local_feed_map(session, user_id=user.id)
    return _to_entry_view(entry, local_feed_map=local_feed_map, include_content=True)


async def update_entries_status(session: AsyncSession, *, user, entry_ids: list[int], status: str) -> None:
    status_value = _normalize_status(status)
    remote_entry_ids = [entry_id for entry_id in entry_ids if not _is_history_entry_id(entry_id)]
    history_entry_ids = [_from_history_entry_id(entry_id) for entry_id in entry_ids if _is_history_entry_id(entry_id)]

    if remote_entry_ids:
        try:
            await _run_user_client_operation(
                user=user,
                operation=lambda client: client.update_entries_status(entry_ids=remote_entry_ids, status=status_value),
            )
        except MinifluxClientError as exc:
            raise _map_miniflux_error(exc) from exc

    if history_entry_ids:
        await feeds_repo.update_history_entries_status(
            session,
            user_id=user.id,
            history_entry_ids=history_entry_ids,
            status=status_value,
        )
        await session.commit()


async def toggle_entry_bookmark(session: AsyncSession, *, user, entry_id: int) -> None:
    if _is_history_entry_id(entry_id):
        item = await feeds_repo.toggle_history_entry_bookmark(
            session,
            user_id=user.id,
            history_entry_id=_from_history_entry_id(entry_id),
        )
        if item is None:
            raise AppError(404, "未找到对应 RSS 条目", code="feed_entry_not_found")
        await session.commit()
        return

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


async def get_entry_for_import(
    session: AsyncSession,
    *,
    user,
    entry_id: int,
) -> dict:
    if _is_history_entry_id(entry_id):
        history_entry = await feeds_repo.get_history_entry(
            session,
            user_id=user.id,
            history_entry_id=_from_history_entry_id(entry_id),
        )
        if history_entry is None:
            raise AppError(404, "未找到对应 RSS 条目", code="feed_entry_not_found")
        feed = await feeds_repo.get_feed_by_local_id(session, user_id=user.id, feed_id=history_entry.feed_id)
        if feed is None:
            raise AppError(404, "未找到对应订阅源", code="feed_not_found")
        return _to_history_raw_entry(history_entry, feed=feed)

    try:
        return await _run_user_client_operation(
            user=user,
            operation=lambda client: client.get_entry(entry_id),
        )
    except MinifluxClientError as exc:
        raise _map_miniflux_error(exc) from exc


async def mark_entries_as_read(session: AsyncSession, *, user, entry_ids: list[int]) -> None:
    await update_entries_status(session, user=user, entry_ids=entry_ids, status="read")


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
