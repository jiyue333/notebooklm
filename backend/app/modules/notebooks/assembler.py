from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from urllib.parse import urlparse

from app.infra.storage.file_store import build_presigned_get_url
from app.modules.notebooks.models import Article
from app.modules.notes.models import Note
from app.modules.notebooks.models import Notebook


def format_notebook_date(value: datetime) -> str:
    localized = value.astimezone()
    return f"{localized.year}年{localized.month}月{localized.day}日"


def format_relative_time(value: datetime | None) -> str:
    if value is None:
        return ''
    now = datetime.now(UTC)
    delta = now - value.astimezone(UTC)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return '刚刚'
    if seconds < 3600:
        return f'{seconds // 60} 分钟前'
    if seconds < 86400:
        return f'{seconds // 3600} 小时前'
    if seconds < 172800:
        return '昨天'
    return f'{seconds // 86400} 天前'


def build_note_view(note: Note) -> dict:
    return {
        'id': note.id,
        'title': note.title,
        'content': note.content_markdown,
        'type': note.note_type,
        'sources': note.source_count,
        'time': format_relative_time(note.updated_at),
        'tags': getattr(note, 'tags_json', None) or [],
    }


def build_article_view(article: Article, *, include_content: bool = True) -> dict:
    published_or_created = article.published_at or article.created_at
    detected_render_mode = guess_render_mode(file_mime=article.file_mime, file_name=article.file_name)
    content_ready = article.parse_status in {'ready', 'completed'} and bool((article.clean_markdown or '').strip())
    source_domain = _extract_source_domain(
        article.source_url,
        preview_markdown=article.preview_markdown,
        title=article.title,
    )
    favicon_url = (
        f"https://www.google.com/s2/favicons?domain={source_domain}&sz=64"
        if source_domain
        else None
    )
    # MinerU can parse PDF into markdown; frontend rendering is unified to markdown/text.
    render_mode = 'markdown'
    file_url = None
    if article.file_storage_key:
        if detected_render_mode == 'pdf':
            file_url = f'/api/notebooks/{article.notebook_id}/articles/{article.id}/file?proxy=1'
        else:
            file_url = build_presigned_get_url(article.file_storage_key)
            if not file_url:
                file_url = f'/api/notebooks/{article.notebook_id}/articles/{article.id}/file'
    if article.parse_status == 'failed':
        processing_hint = article.parse_error_message or '正文解析失败，请稍后重试或重新导入来源。'
    elif content_ready:
        processing_hint = ''
    else:
        processing_hint = '来源已导入，正在抓取和解析正文，请稍后刷新。'
    should_include_content = include_content and content_ready
    toc_items = _coerce_toc_items(article.toc_json)
    if not toc_items:
        toc_items = _extract_toc_from_markdown(article.clean_markdown or "")

    return {
        'id': article.id,
        'title': article.title,
        'type': 'article',
        'inputType': article.input_type,
        'author': article.author,
        'date': published_or_created.isoformat(),
        'sourceUrl': article.source_url,
        'sourceDomain': source_domain,
        'faviconUrl': favicon_url,
        'fileName': article.file_name,
        'selected': False,
        'renderMode': render_mode,
        'fileUrl': file_url,
        'fileMime': article.file_mime,
        'content': article.clean_markdown if should_include_content else '',
        'contentHtml': article.content_html if should_include_content else '',
        # TOC should stay visible even when full body is lazily hydrated.
        # If parser TOC is absent, fallback to heading extraction from markdown.
        'toc': toc_items,
        'readingTimeMinutes': article.reading_time_minutes,
        'contentReady': content_ready,
        'parseStatus': article.parse_status,
        'chunkStatus': article.chunk_status,
        'indexStatus': article.index_status,
        'processingHint': processing_hint,
    }


def _extract_source_domain(
    source_url: str | None,
    *,
    preview_markdown: str | None = None,
    title: str | None = None,
) -> str:
    def _extract_host(raw: str | None) -> str:
        value = str(raw or '').strip()
        if not value:
            return ''
        try:
            parsed = urlparse(value if '://' in value else f'https://{value}')
        except Exception:
            return ''
        return (parsed.hostname or '').strip().lower()

    host = _extract_host(source_url)
    if host:
        return host

    markdown_text = str(preview_markdown or '')
    if markdown_text:
        # [title](url) / 纯 URL / 来源链接：URL
        candidates = re.findall(r'https?://[^\s)\]]+', markdown_text)
        for candidate in candidates:
            host = _extract_host(candidate)
            if host:
                return host

    title_text = str(title or '')
    if title_text:
        match = re.search(r'([a-z0-9-]+\.)+[a-z]{2,}', title_text.lower())
        if match:
            host = _extract_host(match.group(0))
            if host:
                return host
    return ''


def _coerce_toc_items(raw_toc: object) -> list[dict]:
    if not isinstance(raw_toc, list):
        return []
    items: list[dict] = []
    for index, entry in enumerate(raw_toc):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        try:
            level = int(entry.get("level") or 2)
        except Exception:
            level = 2
        level = min(max(level, 1), 6)
        items.append({
            "id": str(entry.get("id") or "").strip(),
            "title": title,
            "level": level,
            "matchIndex": int(entry.get("matchIndex") or index),
        })
    return items


def _extract_toc_from_markdown(markdown_text: str) -> list[dict]:
    text = str(markdown_text or "")
    if not text.strip():
        return []
    items: list[dict] = []
    for index, match in enumerate(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text)):
        level = len(match.group(1))
        title = str(match.group(2) or "").strip()
        if not title:
            continue
        items.append({
            # Keep id empty to let frontend match by heading text.
            "id": "",
            "title": title,
            "level": level,
            "matchIndex": index,
        })
    return items


def build_notebook_summary(notebook: Notebook, *, source_count: int = 0) -> dict:
    return {
        'id': notebook.id,
        'title': notebook.title,
        'emoji': notebook.emoji,
        'color': notebook.color,
        'tags': notebook.tags_json or [],
        'date': format_notebook_date(notebook.created_at),
        'sourceCount': source_count,
        'lastOpenedAt': notebook.last_opened_at.isoformat() if notebook.last_opened_at else None,
        'lastOpenedLabel': format_relative_time(notebook.last_opened_at),
    }


def guess_render_mode(*, file_mime: str | None, file_name: str | None) -> str:
    if file_mime == 'application/pdf':
        return 'pdf'
    if file_name and Path(file_name).suffix.lower() == '.pdf':
        return 'pdf'
    return 'markdown'


def build_notebook_detail(
    notebook: Notebook,
    notes: list[Note],
    articles: list[Article],
    *,
    source_count: int = 0,
    content_article_id: str | None = None,
) -> dict:
    return {
        **build_notebook_summary(notebook, source_count=source_count),
        'articles': [
            build_article_view(
                article,
                include_content=bool(content_article_id and article.id == content_article_id),
            )
            for article in articles
        ],
        'notes': [build_note_view(note) for note in notes],
    }
