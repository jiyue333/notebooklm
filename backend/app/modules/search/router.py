from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.api.deps import current_user_dep, db_session_dep
from app.api.response import success_response
from app.modules.search import repo_article
from app.modules.search.schemas import (
    ImportSearchResultsRequest,
    ManualSourceRequest,
    SearchSourcesRequest,
)
from app.modules.search.service_import import import_results
from app.modules.search.service_manual import create_source, resolve_article_file_path, upload_files
from app.modules.search.service_search import get_search_session, start_search

router = APIRouter(tags=["search"])


@router.post("/notebooks/{notebook_id}/sources/search")
async def search_sources_endpoint(
    notebook_id: str,
    payload: SearchSourcesRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    result = await start_search(
        session,
        user=current_user,
        notebook_id=notebook_id,
        query=payload.query,
        mode=payload.mode,
        max_results=payload.maxResults,
        freshness_hours=payload.freshnessHours,
    )
    return success_response(
        item=result.get("item"),
        items=result.get("items"),
        message=result.get("message", ""),
        meta=result.get("meta"),
    )


@router.post("/notebooks/{notebook_id}/sources/import")
async def import_sources_endpoint(
    notebook_id: str,
    payload: ImportSearchResultsRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await import_results(
        session,
        user=current_user,
        notebook_id=notebook_id,
        search_session_id=payload.searchSessionId,
        search_result_ids=payload.searchResultIds,
    )
    return success_response(item=item)


@router.post("/notebooks/{notebook_id}/sources")
async def create_source_endpoint(
    notebook_id: str,
    payload: ManualSourceRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await create_source(
        session,
        user=current_user,
        notebook_id=notebook_id,
        source_type=payload.sourceType,
        url=payload.url,
        title=payload.title,
        content=payload.content,
    )
    return success_response(item=item)


@router.post("/notebooks/{notebook_id}/sources/upload")
async def upload_sources_endpoint(
    notebook_id: str,
    files: list[UploadFile] = File(...),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    item = await upload_files(
        session,
        user=current_user,
        notebook_id=notebook_id,
        files=files,
    )
    return success_response(item=item)


@router.get("/notebooks/{notebook_id}/articles/{article_id}/file")
async def get_article_file_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await repo_article.get_article(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    file_path = resolve_article_file_path(article)
    if not file_path.exists():
        raise AppError(404, "原始文件不存在", code="article_file_not_found")
    return FileResponse(
        path=file_path,
        media_type=article.file_mime or "application/octet-stream",
        filename=article.file_name or file_path.name,
    )


@router.get("/notebooks/{notebook_id}/search-sessions/{search_session_id}")
async def get_search_session_endpoint(
    notebook_id: str,
    search_session_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    result = await get_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    return success_response(
        item=result.get("item"),
        items=result.get("items"),
        message=result.get("message", ""),
        meta=result.get("meta"),
    )
