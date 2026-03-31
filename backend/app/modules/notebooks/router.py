from __future__ import annotations

import re
from urllib.parse import quote
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
import httpx
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
    get_notebook_article,
    get_notebook_detail,
    invalidate_notebook_detail_cache,
    list_notebooks,
    search_workspace,
    update_notebook,
)

router = APIRouter(prefix='/notebooks', tags=['notebooks'])
_IMAGE_PROXY_TIMEOUT_SECONDS = 12.0
_IMAGE_PROXY_MAX_BYTES = 8 * 1024 * 1024
_IMAGE_PROXY_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)


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
    content_article_id: str | None = Query(default=None, alias='contentArticleId'),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_notebook_detail(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        content_article_id=content_article_id,
    )
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


@router.get('/{notebook_id}/articles/{article_id}')
async def get_article_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await get_notebook_article(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    return success_response(item=item)


@router.get('/media/image-proxy')
async def image_proxy_endpoint(
    url: str = Query(min_length=8, max_length=2048),
):
    target = str(url or '').strip()
    parsed = urlparse(target)
    if parsed.scheme not in {'http', 'https'}:
        raise AppError(422, '仅支持 http/https 图片链接', code='image_proxy_scheme_invalid')
    if not parsed.netloc:
        raise AppError(422, '图片链接无效', code='image_proxy_url_invalid')

    headers = {
        "User-Agent": _IMAGE_PROXY_USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
        "Cache-Control": "no-cache",
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_IMAGE_PROXY_TIMEOUT_SECONDS),
            follow_redirects=True,
        ) as client:
            resp = await client.get(target, headers=headers)
    except Exception as exc:
        raise AppError(502, f'图片拉取失败: {exc}', code='image_proxy_fetch_failed') from exc

    if resp.status_code >= 400:
        raise AppError(502, f'图片拉取失败({resp.status_code})', code='image_proxy_fetch_failed')

    media_type = (resp.headers.get('content-type') or '').split(';')[0].strip().lower()
    if not media_type.startswith('image/'):
        raise AppError(415, '目标不是图片资源', code='image_proxy_invalid_content_type')

    content = resp.content or b''
    if not content:
        raise AppError(502, '图片内容为空', code='image_proxy_empty')
    if len(content) > _IMAGE_PROXY_MAX_BYTES:
        raise AppError(413, '图片过大，暂不支持预览', code='image_proxy_too_large')

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "public, max-age=1800",
        },
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
