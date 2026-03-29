from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.infra.storage.file_store import (
    build_presigned_get_url,
    delete_stored_file,
    load_file_bytes,
    resolve_storage_path,
    stored_file_exists,
)
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.schemas import ArticleUpdateRequest, NotebookCreateRequest, NotebookUpdateRequest
from app.modules.notebooks.service import (
    create_notebook,
    delete_notebook,
    export_notebook_markdown,
    get_notebook_detail,
    invalidate_notebook_detail_cache,
    list_notebooks,
    search_workspace,
    update_notebook,
)

router = APIRouter(prefix='/notebooks', tags=['notebooks'])


def _build_content_disposition(filename: str) -> str:
    normalized = (filename or "notebook.md").strip() or "notebook.md"
    if not normalized.lower().endswith(".md"):
        normalized = f"{normalized}.md"
    ascii_base = re.sub(r"[^A-Za-z0-9._-]+", "_", normalized).strip("._-")
    if not ascii_base or ascii_base.lower() in {"md", ".md"}:
        ascii_base = "notebook"
    ascii_fallback = ascii_base if ascii_base.lower().endswith(".md") else f"{ascii_base}.md"
    encoded = quote(normalized, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


@router.get('')
async def list_notebooks_endpoint(
    query: str = Query(default=''),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items = await list_notebooks(session, user_id=current_user.id, query=query.strip() or None)
    return success_response(items=items)


@router.get('/workspace-search')
async def search_workspace_endpoint(
    query: str = Query(min_length=1),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    items = await search_workspace(session, user_id=current_user.id, query=query)
    return success_response(items=items)


@router.post('')
async def create_notebook_endpoint(
    payload: NotebookCreateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await create_notebook(
        session,
        user_id=current_user.id,
        title=payload.title,
        emoji=None,
        color=None,
        tags=payload.tags,
    )
    return success_response(item=item)


@router.get('/{notebook_id}')
async def get_notebook_detail_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


@router.get('/{notebook_id}/export')
async def export_notebook_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    filename, content = await export_notebook_markdown(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    return Response(
        content=content,
        media_type='text/markdown',
        headers={"Content-Disposition": _build_content_disposition(filename)},
    )


@router.patch('/{notebook_id}')
async def update_notebook_endpoint(
    notebook_id: str,
    payload: NotebookUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await update_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        title=payload.title,
        emoji=payload.emoji,
        color=payload.color,
        tags=payload.tags,
    )
    return success_response(item=item)


@router.delete('/{notebook_id}')
async def delete_notebook_endpoint(
    notebook_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    await delete_notebook(session, user_id=current_user.id, notebook_id=notebook_id)
    return {'success': True}


@router.get('/{notebook_id}/articles/{article_id}/file')
async def get_article_file_endpoint(
    notebook_id: str,
    article_id: str,
    proxy: bool = Query(default=False),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, '未找到对应文章', code='article_not_found')
    if not article.file_storage_key:
        raise AppError(404, '文章没有原始文件', code='article_file_not_found')
    if not stored_file_exists(article.file_storage_key):
        raise AppError(404, '原始文件不存在', code='article_file_not_found')
    if proxy:
        file_bytes = load_file_bytes(article.file_storage_key)
        headers = {}
        if article.file_name:
            headers['Content-Disposition'] = f'inline; filename="{article.file_name}"'
        return Response(
            content=file_bytes,
            media_type=article.file_mime or 'application/octet-stream',
            headers=headers,
        )
    presigned_url = build_presigned_get_url(article.file_storage_key)
    if presigned_url:
        return RedirectResponse(url=presigned_url, status_code=307)
    file_path = resolve_storage_path(article.file_storage_key)
    return FileResponse(
        path=file_path,
        media_type=article.file_mime or 'application/octet-stream',
        filename=article.file_name or file_path.name,
    )


@router.patch('/{notebook_id}/articles/{article_id}')
async def update_article_endpoint(
    notebook_id: str,
    article_id: str,
    payload: ArticleUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, '未找到对应文章', code='article_not_found')
    article.title = payload.title.strip()
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


@router.delete('/{notebook_id}/articles/{article_id}')
async def delete_article_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, '未找到对应文章', code='article_not_found')
    if article.file_storage_key and stored_file_exists(article.file_storage_key):
        delete_stored_file(article.file_storage_key)
    await notebooks_repo.delete_article(session, article)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)
