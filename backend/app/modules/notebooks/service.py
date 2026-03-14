from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.cache import delete_keys, get_json, notebook_detail_key, set_json
from app.infra.storage.file_store import is_object_storage_enabled
from app.modules.notes import repo as notes_repo
from app.modules.notebooks import assembler, repo
from app.modules.search.articles import repo as repo_article


async def list_notebooks(session: AsyncSession, *, user_id: str, query: str | None = None) -> list[dict]:
    notebooks = await repo.list_notebooks(session, user_id=user_id, query=query)
    counts = await repo_article.count_articles_by_notebook_ids(
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
) -> dict:
    notebook = await repo.create_notebook(
        session,
        user_id=user_id,
        title=title.strip(),
        emoji=emoji,
        color=color,
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


async def get_notebook_detail(session: AsyncSession, *, user_id: str, notebook_id: str) -> dict:
    cache_key = notebook_detail_key(user_id=user_id, notebook_id=notebook_id)
    cached = await get_json(cache_key)
    if isinstance(cached, dict) and not _should_refresh_cached_notebook_detail(cached):
        return cached

    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    notes = await notes_repo.list_notes(session, user_id=user_id, notebook_id=notebook_id)
    articles = await repo_article.list_articles_by_notebook(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
    )
    detail = assembler.build_notebook_detail(notebook, notes, articles, source_count=len(articles))
    await set_json(cache_key, detail, ttl_seconds=_resolve_notebook_detail_ttl(detail))
    return detail


async def update_notebook(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    title: str | None,
    emoji: str | None,
    color: str | None,
) -> dict:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    if title is not None:
        notebook.title = title.strip()
    if emoji is not None:
        notebook.emoji = emoji
    if color is not None:
        notebook.color = color

    await session.commit()
    await session.refresh(notebook)
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return assembler.build_notebook_summary(notebook)


async def delete_notebook(session: AsyncSession, *, user_id: str, notebook_id: str) -> None:
    notebook = await repo.get_notebook(session, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")
    await repo.delete_notebook(session, notebook)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)


async def invalidate_notebook_detail_cache(*, user_id: str, notebook_id: str) -> None:
    await delete_keys([notebook_detail_key(user_id=user_id, notebook_id=notebook_id)])


def _resolve_notebook_detail_ttl(detail: dict) -> int:
    settings = get_settings()
    has_pending_articles = any(
        not article.get("contentReady") and article.get("parseStatus") != "failed"
        for article in detail.get("articles", [])
    )
    if has_pending_articles:
        return settings.cache_ttl_notebook_detail_pending_seconds
    return settings.cache_ttl_notebook_detail_seconds


def _should_refresh_cached_notebook_detail(detail: dict) -> bool:
    if not is_object_storage_enabled():
        return False
    articles = detail.get("articles", [])
    return any(
        isinstance(article, dict)
        and isinstance(article.get("fileUrl"), str)
        and article["fileUrl"].startswith("/api/notebooks/")
        and not (
            article.get("renderMode") == "pdf"
            or article.get("fileMime") == "application/pdf"
        )
        for article in articles
    )
