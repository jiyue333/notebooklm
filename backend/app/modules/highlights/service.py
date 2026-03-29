from __future__ import annotations

from app.api.errors import AppError
from app.modules.highlights import repo
from app.modules.notebooks import repo as notebooks_repo

_ALLOWED_HIGHLIGHT_COLORS = {"yellow", "blue", "green", "pink", "purple", "orange"}


def _normalize_color(value: str | None) -> str:
    normalized = str(value or "yellow").strip().lower()
    if normalized not in _ALLOWED_HIGHLIGHT_COLORS:
        return "yellow"
    return normalized


def _normalize_comment(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:2000] or None


def _build_highlight_view(item) -> dict:
    return {
        "id": item.id,
        "notebookId": item.notebook_id,
        "articleId": item.article_id,
        "text": item.selected_text,
        "color": item.color,
        "comment": item.comment_text or "",
        "startOffset": item.start_offset,
        "endOffset": item.end_offset,
        "occurrenceIndex": item.occurrence_index,
        "createdAt": item.created_at.isoformat() if item.created_at else None,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }


async def list_article_highlights(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
) -> list[dict]:
    article = await notebooks_repo.get_article(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    items = await repo.list_article_highlights(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    return [_build_highlight_view(item) for item in items]


async def create_article_highlight(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    text: str,
    color: str | None,
    comment: str | None,
    start_offset: int | None,
    end_offset: int | None,
    occurrence_index: int | None,
) -> dict:
    article = await notebooks_repo.get_article(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    normalized_text = text.strip()
    if not normalized_text:
        raise AppError(422, "高亮文本不能为空", code="highlight_text_required")

    if start_offset is not None and end_offset is not None and end_offset < start_offset:
        raise AppError(422, "高亮偏移范围无效", code="invalid_highlight_offset")

    highlight = await repo.create_highlight(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
        selected_text=normalized_text,
        color=_normalize_color(color),
        comment_text=_normalize_comment(comment),
        start_offset=start_offset,
        end_offset=end_offset,
        occurrence_index=occurrence_index,
    )
    await session.commit()
    await session.refresh(highlight)
    return _build_highlight_view(highlight)


async def update_article_highlight(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    highlight_id: str,
    color: str | None,
    comment: str | None,
) -> dict:
    highlight = await repo.get_highlight(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
        highlight_id=highlight_id,
    )
    if highlight is None:
        raise AppError(404, "未找到对应高亮", code="highlight_not_found")

    if color is not None:
        highlight.color = _normalize_color(color)
    if comment is not None:
        highlight.comment_text = _normalize_comment(comment)

    await session.commit()
    await session.refresh(highlight)
    return _build_highlight_view(highlight)


async def delete_article_highlight(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    highlight_id: str,
) -> None:
    highlight = await repo.get_highlight(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
        highlight_id=highlight_id,
    )
    if highlight is None:
        raise AppError(404, "未找到对应高亮", code="highlight_not_found")

    await repo.delete_highlight(session, highlight)
    await session.commit()

