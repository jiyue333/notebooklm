"""Sources API – 导入搜索结果、手动添加来源、文件上传。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.infra.storage.file_store import build_storage_key, store_file_bytes
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article
from app.modules.notebooks.service import get_notebook_detail, invalidate_notebook_detail_cache
from app.modules.agent.search import repo as search_repo

router = APIRouter(tags=["sources"])

_SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}


# ── Schemas ─────────────────────────────────────────────────────────────────

class ImportSearchResultsRequest(BaseModel):
    searchSessionId: str
    searchResultIds: list[str] = Field(min_length=1)


class ManualSourceRequest(BaseModel):
    sourceType: str  # "web" | "text"
    url: str | None = None
    title: str | None = None
    content: str | None = None


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

    results = await search_repo.list_search_results(
        session, search_session_id=search_session.id,
    )
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
        store_file_bytes(
            storage_key=storage_key,
            data=data,
            content_type=upload.content_type or "application/octet-stream",
        )
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
