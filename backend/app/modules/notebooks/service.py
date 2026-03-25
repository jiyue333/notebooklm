from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.cache import delete_keys, get_json, notebook_detail_key, set_json
from app.infra.storage.file_store import is_object_storage_enabled
from app.modules.notes import repo as notes_repo
from app.modules.notebooks import assembler, repo


def _normalize_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    normalized: list[str] = []
    for item in tags:
        tag = str(item or '').strip()
        if not tag:
            continue
        if tag not in normalized:
            normalized.append(tag)
    return normalized[:8]


async def list_notebooks(session: AsyncSession, *, user_id: str, query: str | None = None) -> list[dict]:
    notebooks = await repo.list_notebooks(session, user_id=user_id, query=query)
    counts = await repo.count_articles_by_notebook_ids(
        session,
        user_id=user_id,
        notebook_ids=[notebook.id for notebook in notebooks],
    )
    return [
        assembler.build_notebook_summary(notebook, source_count=counts.get(notebook.id, 0))
        for notebook in notebooks
    ]


async def create_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    title: str,
    emoji: str | None,
    color: str | None,
    tags: list[str] | None = None,
) -> dict:
    normalized_title = title.strip()
    if await _title_exists(session, user_id=user_id, title=normalized_title):
        raise AppError(409, '笔记本标题已存在', code='notebook_title_conflict')

    notebook = await repo.create_notebook(
        session,
        user_id=user_id,
        title=normalized_title,
        emoji=emoji,
        color=color,
        tags=_normalize_tags(tags),
    )
    await session.commit()
    await session.refresh(notebook)
    detail = assembler.build_notebook_detail(notebook, [], [], source_count=0)
    await set_json(
        notebook_detail_key(user_id=user_id, notebook_id=notebook.id),
        detail,
        ttl_seconds=_resolve_notebook_detail_ttl(detail),
    )
    return detail


async def get_notebook_detail(session: AsyncSession, *, user_id: str, notebook_id: str, mark_opened: bool = True) -> dict:
    cache_key = notebook_detail_key(user_id=user_id, notebook_id=notebook_id)
    cached = await get_json(cache_key)
    if isinstance(cached, dict) and not _should_refresh_cached_notebook_detail(cached):
        if mark_opened:
            notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
            if notebook is not None:
                await repo.mark_notebook_opened(session, notebook=notebook, opened_at=datetime.now(UTC))
                await session.commit()
        return cached

    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')

    if mark_opened:
        await repo.mark_notebook_opened(session, notebook=notebook, opened_at=datetime.now(UTC))

    notes = await notes_repo.list_notes(session, user_id=user_id, notebook_id=notebook_id)
    articles = await repo.list_articles_by_notebook(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
    )
    detail = assembler.build_notebook_detail(notebook, notes, articles, source_count=len(articles))
    await set_json(cache_key, detail, ttl_seconds=_resolve_notebook_detail_ttl(detail))
    await session.commit()
    return detail


async def update_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    title: str | None,
    emoji: str | None,
    color: str | None,
    tags: list[str] | None = None,
) -> dict:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')

    if title is not None:
        normalized_title = title.strip()
        title_owner = await repo.get_notebook_by_title(session, user_id=user_id, title=normalized_title)
        if title_owner is not None and title_owner.id != notebook_id:
            raise AppError(409, '笔记本标题已存在', code='notebook_title_conflict')
        notebook.title = normalized_title
    if emoji is not None:
        notebook.emoji = emoji
    if color is not None:
        notebook.color = color
    if tags is not None:
        notebook.tags_json = _normalize_tags(tags)

    await session.commit()
    await session.refresh(notebook)
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return assembler.build_notebook_summary(notebook)


async def delete_notebook(session: AsyncSession, *, user_id: str, notebook_id: str) -> None:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, '未找到对应的笔记本', code='notebook_not_found')
    await repo.delete_notebook(session, notebook)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)


async def search_workspace(
    session: AsyncSession,
    *,
    user_id: str,
    query: str,
) -> list[dict]:
    return await repo.search_notebooks_and_articles(session, user_id=user_id, query=query)


async def invalidate_notebook_detail_cache(*, user_id: str, notebook_id: str) -> None:
    await delete_keys([notebook_detail_key(user_id=user_id, notebook_id=notebook_id)])


async def _title_exists(session: AsyncSession, *, user_id: str, title: str) -> bool:
    if not title:
        return False
    return await repo.get_notebook_by_title(session, user_id=user_id, title=title) is not None


def _resolve_notebook_detail_ttl(detail: dict) -> int:
    settings = get_settings()
    has_pending_articles = any(
        not article.get('contentReady') and article.get('parseStatus') != 'failed'
        for article in detail.get('articles', [])
    )
    if has_pending_articles:
        return settings.cache_ttl_notebook_detail_pending_seconds
    return settings.cache_ttl_notebook_detail_seconds


def _should_refresh_cached_notebook_detail(detail: dict) -> bool:
    if not is_object_storage_enabled():
        return False
    articles = detail.get('articles', [])
    return any(
        isinstance(article, dict)
        and isinstance(article.get('fileUrl'), str)
        and article['fileUrl'].startswith('/api/notebooks/')
        and not (
            article.get('renderMode') == 'pdf'
            or article.get('fileMime') == 'application/pdf'
        )
        for article in articles
    )
