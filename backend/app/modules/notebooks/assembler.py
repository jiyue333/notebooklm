from __future__ import annotations

from datetime import UTC, datetime

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


def build_notebook_summary(notebook: Notebook, *, source_count: int = 0) -> dict:
    return {
        "id": notebook.id,
        "title": notebook.title,
        "emoji": notebook.emoji,
        "color": notebook.color,
        "date": format_notebook_date(notebook.created_at),
        "sourceCount": source_count,
    }


def build_notebook_detail(notebook: Notebook, notes: list[Note], *, source_count: int = 0) -> dict:
    return {
        **build_notebook_summary(notebook, source_count=source_count),
        "articles": [],
        "notes": [build_note_view(note) for note in notes],
    }
