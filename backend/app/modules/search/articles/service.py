from __future__ import annotations

from app.api.errors import AppError
from app.infra.storage.file_store import delete_stored_file, stored_file_exists
from app.modules.notebooks.service import get_notebook_detail, invalidate_notebook_detail_cache
from app.modules.search.articles import repo


async def rename_article(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
    title: str,
) -> dict:
    article = await repo.get_article(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")

    next_title = title.strip()
    if not next_title:
        raise AppError(422, "标题不能为空", code="article_title_required")

    article.title = next_title
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return await get_notebook_detail(session, user_id=user_id, notebook_id=notebook_id)


async def remove_article(
    session,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str,
) -> dict:
    article = await repo.get_article(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")

    if article.file_storage_key and stored_file_exists(article.file_storage_key):
        delete_stored_file(article.file_storage_key)

    await repo.delete_article(session, article)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=user_id, notebook_id=notebook_id)
    return await get_notebook_detail(session, user_id=user_id, notebook_id=notebook_id)
