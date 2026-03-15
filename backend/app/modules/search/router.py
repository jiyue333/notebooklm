"""Search & source management API endpoints.

Restored endpoints:
  POST /notebooks/{id}/sources/search        – start a search
  POST /notebooks/{id}/sources/import        – import search results
  POST /notebooks/{id}/sources               – manual add (URL/text)
  POST /notebooks/{id}/sources/upload        – upload files
  GET  /notebooks/{id}/articles/{aid}/file   – get article file
  PATCH /notebooks/{id}/articles/{aid}       – rename article
  DELETE /notebooks/{id}/articles/{aid}      – delete article
  GET  /notebooks/{id}/search-sessions/{sid} – poll search session
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import UTC, datetime
import hashlib

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.infra.storage.file_store import (
    build_presigned_get_url,
    build_storage_key,
    delete_stored_file,
    load_file_bytes,
    resolve_storage_path,
    store_file_bytes,
    stored_file_exists,
)
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article
from app.modules.notebooks.service import get_notebook_detail, invalidate_notebook_detail_cache
from app.modules.search.sessions import repo as search_repo
from app.modules.search.sessions.schemas import SearchRequest, SearchResponse
from app.modules.search.sessions.service import get_search_session, start_search
from app.modules.settings.runtime import resolve_search_api_key

router = APIRouter(tags=["search"])

_SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}


# ── Schemas for restored endpoints ─────────────────────────────────────────

class ImportSearchResultsRequest(BaseModel):
    searchSessionId: str
    searchResultIds: list[str] = Field(min_length=1)


class ManualSourceRequest(BaseModel):
    sourceType: str  # "web" | "text"
    url: str | None = None
    title: str | None = None
    content: str | None = None


class ArticleSourceUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


# ── Search ─────────────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/search")
async def search_sources_endpoint(
    notebook_id: str,
    payload: SearchRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    exa_api_key, _key_source = resolve_search_api_key(current_user)
    if not exa_api_key:
        raise AppError(422, "请先在设置里配置 Exa API Key", code="search_api_key_required")

    existing_articles = await notebooks_repo.list_articles_by_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    existing_urls = [a.source_url for a in existing_articles if a.source_url]
    existing_titles = [a.title for a in existing_articles if a.title]

    return await start_search(
        session,
        user=current_user,
        notebook_id=notebook_id,
        query=payload.query,
        mode=payload.mode,
        max_results=payload.maxResults,
        freshness_hours=payload.freshnessHours,
        exa_api_key=exa_api_key,
        notebook_title=notebook.title or "",
        existing_article_urls=existing_urls,
        existing_article_titles=existing_titles,
    )


@router.get("/notebooks/{notebook_id}/search-sessions/{search_session_id}")
async def get_search_session_endpoint(
    notebook_id: str,
    search_session_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
) -> SearchResponse:
    return await get_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )


# ── Import search results (async) ──────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/import")
async def import_sources_endpoint(
    notebook_id: str,
    payload: ImportSearchResultsRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    search_session = await search_repo.get_search_session(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
        search_session_id=payload.searchSessionId,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")

    results = await search_repo.list_search_results(session, search_session_id=search_session.id)
    result_map = {r.id: r for r in results}
    now = datetime.now(UTC)
    jobs = []
    for rid in payload.searchResultIds:
        sr = result_map.get(rid)
        if sr is None:
            continue
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="search_result",
            dedupe_key=f"url:{sr.url_hash}",
            title=sr.title,
            source_url=sr.raw_url,
            author=sr.author,
            published_at=sr.published_at,
            preview_markdown=sr.description,
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
        session.add(article)
        await session.flush()
        job = await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=search_session.id,
            dedupe_key=f"ingest:{article.id}",
            payload_json={"articleId": article.id},
            created_at=now,
        )
        jobs.append(job)
    await session.commit()
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


# ── Manual source – URL / text (async) ─────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources")
async def create_source_endpoint(
    notebook_id: str,
    payload: ManualSourceRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    now = datetime.now(UTC)
    if payload.sourceType == "text":
        title = (payload.title or "粘贴文字来源").strip()
        dedupe_key = f"text:{hashlib.sha256((payload.content or '').encode()).hexdigest()}"
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="text",
            dedupe_key=dedupe_key,
            title=title,
            raw_text_input=payload.content,
            preview_markdown=f"# {title}\n\n{(payload.content or '')[:200]}...",
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
    elif payload.sourceType == "web":
        if not payload.url:
            raise AppError(422, "请输入网站链接", code="url_required")
        title = (payload.title or payload.url).strip()
        dedupe_key = f"url:{hashlib.sha256(payload.url.strip().encode()).hexdigest()}"
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="url",
            dedupe_key=dedupe_key,
            title=title,
            source_url=payload.url.strip(),
            preview_markdown=f"# {title}\n\n来源链接：{payload.url.strip()}\n\n等待解析中。",
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
    else:
        raise AppError(422, "不支持的来源类型", code="invalid_source_type")

    session.add(article)
    await session.flush()
    job = await jobs_repo.create_article_ingest_job(
        session,
        article_id=article.id,
        search_session_id=None,
        dedupe_key=f"ingest:{article.id}",
        payload_json={"articleId": article.id},
        created_at=now,
    )
    await session.commit()
    await job_publisher.publish_jobs(session, [job])
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


# ── File upload (async) ────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/upload")
async def upload_sources_endpoint(
    notebook_id: str,
    files: list[UploadFile] = File(...),
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    now = datetime.now(UTC)
    jobs = []
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        file_name = (upload.filename or "未命名文件").strip()
        file_ext = Path(file_name).suffix.lower()
        if file_ext not in _SUPPORTED_UPLOAD_EXTENSIONS:
            raise AppError(
                422,
                f"暂不支持上传该文件类型：{file_name}",
                code="unsupported_upload_type",
                meta={"supportedExtensions": sorted(_SUPPORTED_UPLOAD_EXTENSIONS)},
            )
        dedupe_key = f"file:{hashlib.sha256(data).hexdigest()}"
        temp_article_id = hashlib.sha256(data).hexdigest()[:32]
        storage_key = build_storage_key(
            notebook_id=notebook_id,
            article_id=temp_article_id,
            filename=file_name,
        )
        store_file_bytes(storage_key=storage_key, data=data, content_type=upload.content_type or "application/octet-stream")
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="file",
            dedupe_key=dedupe_key,
            title=file_name,
            file_name=file_name,
            file_mime=upload.content_type,
            file_size=len(data),
            file_storage_key=storage_key,
            preview_markdown=f"# {file_name}\n\n文件已上传，正在解析内容。",
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
        session.add(article)
        await session.flush()
        job = await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=None,
            dedupe_key=f"ingest:{article.id}",
            payload_json={"articleId": article.id},
            created_at=now,
        )
        jobs.append(job)
    await session.commit()
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


# ── Article file access ────────────────────────────────────────────────────

@router.get("/notebooks/{notebook_id}/articles/{article_id}/file")
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
        raise AppError(404, "未找到对应文章", code="article_not_found")
    if not article.file_storage_key:
        raise AppError(404, "文章没有原始文件", code="article_file_not_found")
    if not stored_file_exists(article.file_storage_key):
        raise AppError(404, "原始文件不存在", code="article_file_not_found")
    if proxy:
        file_bytes = load_file_bytes(article.file_storage_key)
        headers = {}
        if article.file_name:
            headers["Content-Disposition"] = f'inline; filename="{article.file_name}"'
        return Response(
            content=file_bytes,
            media_type=article.file_mime or "application/octet-stream",
            headers=headers,
        )
    presigned_url = build_presigned_get_url(article.file_storage_key)
    if presigned_url:
        return RedirectResponse(url=presigned_url, status_code=307)
    file_path = resolve_storage_path(article.file_storage_key)
    return FileResponse(
        path=file_path,
        media_type=article.file_mime or "application/octet-stream",
        filename=article.file_name or file_path.name,
    )


# ── Article rename ─────────────────────────────────────────────────────────

@router.patch("/notebooks/{notebook_id}/articles/{article_id}")
async def update_article_source_endpoint(
    notebook_id: str,
    article_id: str,
    payload: ArticleSourceUpdateRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(
        session, user_id=current_user.id, notebook_id=notebook_id, article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    article.title = payload.title.strip()
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)


# ── Article delete ─────────────────────────────────────────────────────────

@router.delete("/notebooks/{notebook_id}/articles/{article_id}")
async def delete_article_source_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    article = await notebooks_repo.get_article(
        session, user_id=current_user.id, notebook_id=notebook_id, article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    if article.file_storage_key and stored_file_exists(article.file_storage_key):
        delete_stored_file(article.file_storage_key)
    await notebooks_repo.delete_article(session, article)
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)
