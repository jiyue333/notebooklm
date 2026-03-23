from __future__ import annotations

from datetime import UTC, datetime

from pathlib import Path

from app.infra.storage.file_store import build_presigned_get_url
from app.modules.notebooks.models import Article
from app.modules.notes.models import Note
from app.modules.notebooks.models import Notebook


def format_notebook_date(value: datetime) -> str:
    localized = value.astimezone()
    return f"{localized.year}年{localized.month}月{localized.day}日"


def format_relative_time(value: datetime) -> str:
    now = datetime.now(UTC)
    delta = now - value.astimezone(UTC)
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{seconds // 60} 分钟前"
    if seconds < 86400:
        return f"{seconds // 3600} 小时前"
    if seconds < 172800:
        return "昨天"
    return f"{seconds // 86400} 天前"


def build_note_view(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "content": note.content_markdown,
        "type": note.note_type,
        "sources": note.source_count,
        "time": format_relative_time(note.updated_at),
    }


def build_article_view(article: Article) -> dict:
    published_or_created = article.published_at or article.created_at
    render_mode = guess_render_mode(file_mime=article.file_mime, file_name=article.file_name)
    content_ready = article.parse_status in {"ready", "completed"} and bool((article.clean_markdown or "").strip())
    file_url = None
    if article.file_storage_key:
        if render_mode == "pdf":
            file_url = f"/api/notebooks/{article.notebook_id}/articles/{article.id}/file?proxy=1"
        else:
            file_url = build_presigned_get_url(article.file_storage_key)
            if not file_url:
                file_url = f"/api/notebooks/{article.notebook_id}/articles/{article.id}/file"
    if article.parse_status == "failed":
        processing_hint = article.parse_error_message or "正文解析失败，请稍后重试或重新导入来源。"
    elif content_ready:
        processing_hint = ""
    else:
        processing_hint = "来源已导入，正在抓取和解析正文，请稍后刷新。"
    return {
        "id": article.id,
        "title": article.title,
        "type": "article",
        "author": article.author,
        "date": published_or_created.isoformat(),
        "sourceUrl": article.source_url,
        "selected": False,
        "renderMode": render_mode,
        "fileUrl": file_url,
        "fileMime": article.file_mime,
        "content": article.clean_markdown if content_ready else "",
        "contentHtml": article.content_html if content_ready else "",
        "toc": article.toc_json if content_ready else [],
        "readingTimeMinutes": article.reading_time_minutes,
        "contentReady": content_ready,
        "parseStatus": article.parse_status,
        "chunkStatus": article.chunk_status,
        "indexStatus": article.index_status,
        "processingHint": processing_hint,
    }


def build_notebook_summary(notebook: Notebook, *, source_count: int = 0) -> dict:
    return {
        "id": notebook.id,
        "title": notebook.title,
        "emoji": notebook.emoji,
        "color": notebook.color,
        "date": format_notebook_date(notebook.created_at),
        "sourceCount": source_count,
    }


def guess_render_mode(*, file_mime: str | None, file_name: str | None) -> str:
    if file_mime == "application/pdf":
        return "pdf"
    if file_name and Path(file_name).suffix.lower() == ".pdf":
        return "pdf"
    return "markdown"


def build_notebook_detail(
    notebook: Notebook,
    notes: list[Note],
    articles: list[Article],
    *,
    source_count: int = 0,
) -> dict:
    return {
        **build_notebook_summary(notebook, source_count=source_count),
        "articles": [build_article_view(article) for article in articles],
        "notes": [build_note_view(note) for note in notes],
    }
