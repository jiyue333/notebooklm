"""Sources API – 导入搜索结果、手动添加来源、文件上传。"""

from __future__ import annotations

import asyncio
import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.infra.ai.lite_models import build_lite_llm
from app.infra.storage.file_store import build_storage_key, store_file_bytes
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.feeds import service as feeds_service
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article
from app.modules.notebooks.service import get_notebook_detail, invalidate_notebook_detail_cache
from app.modules.agent.search import repo as search_repo

router = APIRouter(tags=["sources"])
logger = structlog.get_logger(__name__)

_SUPPORTED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md"}
_AUTO_TITLE_MODEL_TIMEOUT_SECONDS = 6.0
_AUTO_TITLE_MAX_LENGTH = 80
_AUTO_TITLE_SYSTEM_PROMPT = (
    "你是文档来源标题生成器。"
    "请输出单行标题，不超过18个中文字符或8个英文单词。"
    "不要输出引号、序号、句号或额外说明。"
)
_STRIP_HTML_RE = re.compile(r"<[^>]+>")


def _strip_markdown_prefix(value: str) -> str:
    return re.sub(r"^[#>*\-\s\d\.\)\(]+", "", value).strip()


def _sanitize_title(value: str | None) -> str:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    normalized = normalized.strip("'\"`“”‘’")
    normalized = _strip_markdown_prefix(normalized)
    return normalized[:_AUTO_TITLE_MAX_LENGTH]


def _flatten_llm_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def _fallback_title_from_url(url: str | None) -> str:
    normalized_url = (url or "").strip()
    if not normalized_url:
        return "网页来源"
    parsed = urlparse(normalized_url if "://" in normalized_url else f"https://{normalized_url}")
    host = (parsed.netloc or parsed.path.split("/")[0]).replace("www.", "").strip()
    path_candidate = unquote((parsed.path or "").strip("/").split("/")[-1])
    path_candidate = _sanitize_title(path_candidate.replace("-", " ").replace("_", " "))
    if host and path_candidate and path_candidate.lower() not in {"index", "home"}:
        return _sanitize_title(f"{host} · {path_candidate}")
    if host:
        return _sanitize_title(host)
    return _sanitize_title(normalized_url) or "网页来源"


def _fallback_title_from_text(content: str | None) -> str:
    normalized_content = (content or "").strip()
    if not normalized_content:
        return "粘贴文字来源"
    for raw_line in normalized_content.splitlines():
        line = _sanitize_title(raw_line)
        if line:
            return line
    return "粘贴文字来源"


def _build_rss_preview_markdown(*, title: str, url: str | None, content_html: str | None) -> str:
    plain = _STRIP_HTML_RE.sub(" ", str(content_html or ""))
    plain = " ".join(plain.split())
    if len(plain) > 260:
        plain = f"{plain[:260].rstrip()}..."
    normalized_url = (url or "").strip()
    return f"# {title}\n\n来源链接：{normalized_url}\n\n{plain or '等待解析中。'}"


def _parse_iso_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


async def _generate_title_with_lite_model(
    *,
    source_type: str,
    url: str | None = None,
    content: str | None = None,
) -> str | None:
    model = build_lite_llm()
    if model is None:
        return None

    from langchain_core.messages import HumanMessage, SystemMessage

    if source_type == "web":
        user_prompt = (
            "根据下面网页链接生成一个简短中文标题。\n"
            f"URL: {(url or '').strip()}\n"
            "仅输出标题。"
        )
    else:
        excerpt = (content or "").strip()[:1400]
        user_prompt = (
            "根据下面文本内容生成一个简短中文标题。\n"
            f"内容:\n{excerpt}\n"
            "仅输出标题。"
        )

    try:
        response = await asyncio.wait_for(
            model.ainvoke([
                SystemMessage(content=_AUTO_TITLE_SYSTEM_PROMPT),
                HumanMessage(content=user_prompt),
            ]),
            timeout=_AUTO_TITLE_MODEL_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    generated = _sanitize_title(_flatten_llm_content(getattr(response, "content", "")))
    return generated or None


async def _resolve_manual_source_title(
    *,
    source_type: str,
    provided_title: str | None,
    url: str | None = None,
    content: str | None = None,
) -> str:
    normalized_title = _sanitize_title(provided_title)
    if normalized_title:
        return normalized_title

    fallback = (
        _fallback_title_from_url(url)
        if source_type == "web"
        else _fallback_title_from_text(content)
    )
    generated = await _generate_title_with_lite_model(
        source_type=source_type,
        url=url,
        content=content,
    )
    return generated or fallback


async def _submit_url_batches_with_partial_retry(
    *,
    mineru,
    items: list[tuple[Article, str]],
    model_version: str,
) -> tuple[list[tuple[Article, str, str]], list[tuple[Article, str, str]]]:
    queued: list[tuple[Article, str, str]] = []
    failed: list[tuple[Article, str, str]] = []

    async def _submit_chunk(chunk: list[tuple[Article, str]], *, depth: int) -> None:
        if not chunk:
            return

        batch_items = [{"url": url, "data_id": article.id} for article, url in chunk]
        try:
            batch_id = await mineru.submit_url_batch(batch_items, model_version=model_version)
        except Exception as exc:
            error_text = str(exc)[:200] or "unknown submit failure"
            logger.warning(
                "sources.import.mineru_batch_submit_failed",
                count=len(chunk),
                depth=depth,
                error=error_text,
            )
            if len(chunk) == 1:
                article, url = chunk[0]
                failed.append((article, url, error_text))
                return

            split_at = max(1, len(chunk) // 2)
            logger.info(
                "sources.import.mineru_batch_split_retry",
                depth=depth,
                left_count=split_at,
                right_count=len(chunk) - split_at,
            )
            await _submit_chunk(chunk[:split_at], depth=depth + 1)
            await _submit_chunk(chunk[split_at:], depth=depth + 1)
            return

        queued.extend((article, url, batch_id) for article, url in chunk)

    await _submit_chunk(items, depth=0)
    return queued, failed


# ── Schemas ─────────────────────────────────────────────────────────────────

class ImportSearchResultsRequest(BaseModel):
    searchSessionId: str
    searchResultIds: list[str] = Field(min_length=1)


class ManualSourceRequest(BaseModel):
    sourceType: str  # "web" | "text"
    url: str | None = None
    title: str | None = None
    content: str | None = None


class ImportRssEntriesRequest(BaseModel):
    entryIds: list[int] = Field(min_length=1, max_length=50)


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
    if search_session.status == "failed":
        raise AppError(409, "该搜索会话已失败，请重新搜索后再导入", code="search_session_failed")

    results = await search_repo.list_search_results(
        session, search_session_id=search_session.id,
    )
    if search_session.status in {"queued", "running"} and not results:
        raise AppError(409, "搜索仍在进行中，请稍后再导入", code="search_session_pending")

    result_map = {r.id: r for r in results}
    missing_result_ids = [rid for rid in payload.searchResultIds if rid not in result_map]
    if missing_result_ids:
        raise AppError(
            422,
            "部分搜索结果已失效，请重新搜索后再导入",
            code="search_results_not_found",
            meta={"missingResultIds": missing_result_ids},
        )
    now = datetime.now(UTC)
    existing_articles = await notebooks_repo.list_articles_by_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    existing_dedupe_keys = {article.dedupe_key for article in existing_articles if article.dedupe_key}

    # ====== step 1 创建 Article 记录 ======
    articles_for_batch: list[tuple[Article, str]] = []  # (article, raw_url)
    for rid in payload.searchResultIds:
        sr = result_map.get(rid)
        if sr is None:
            continue
        normalized_source_url = str(sr.raw_url or "").strip()
        if not normalized_source_url and sr.domain:
            normalized_source_url = f"https://{str(sr.domain).strip()}"
        if not normalized_source_url:
            logger.warning(
                "sources.import.skip_missing_url",
                notebook_id=notebook_id,
                search_result_id=rid,
                title=sr.title,
            )
            continue
        url_hash = str(sr.url_hash or "").strip()
        if not url_hash:
            url_hash = hashlib.sha256(normalized_source_url.encode("utf-8")).hexdigest()
        dedupe_key = f"url:{url_hash}"
        if dedupe_key in existing_dedupe_keys:
            continue
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="search_result",
            dedupe_key=dedupe_key,
            title=sr.title,
            source_url=normalized_source_url or None,
            author=sr.author,
            published_at=sr.published_at,
            preview_markdown=sr.description,
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
        session.add(article)
        await session.flush()
        articles_for_batch.append((article, normalized_source_url))
        existing_dedupe_keys.add(dedupe_key)

    if not articles_for_batch:
        item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
        return success_response(
            item=item,
            message="选中的来源已存在，无需重复导入",
            meta={"skippedDuplicate": True},
        )

    # ====== step 2 batch 提交所有 URL 到 MinerU（失败时拆分重试） ======
    from app.infra.providers.mineru.client import MinerUCloudClient

    mineru = MinerUCloudClient()
    queued_batch_items, failed_batch_items = await _submit_url_batches_with_partial_retry(
        mineru=mineru,
        items=articles_for_batch,
        model_version="MinerU-HTML",
    )

    for article, _url, _error in failed_batch_items:
        article.parse_status = "failed"
        article.parse_error_tag = "mineru_batch_submit_failed"
        article.parse_error_message = "来源批量提交解析任务失败，请稍后重试。"
        article.chunk_status = "failed"
        article.index_status = "failed"

    if not queued_batch_items:
        for article, _url in articles_for_batch:
            article.parse_status = "failed"
            article.parse_error_tag = "mineru_batch_submit_failed"
            article.parse_error_message = "来源批量提交解析任务失败，请稍后重试。"
            article.chunk_status = "failed"
            article.index_status = "failed"
        await session.commit()
        await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
        item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
        return success_response(
            item=item,
            message="来源导入成功，但批量解析提交失败，请重试失败条目。",
            meta={
                "queuedCount": 0,
                "failedCount": len(articles_for_batch),
                "failedReason": "mineru_batch_submit_failed",
            },
        )

    # ====== step 3 创建 Job，带上 batch 信息 ======
    jobs = []
    for article, _url, mineru_batch_id in queued_batch_items:
        payload_json: dict = {"articleId": article.id}
        payload_json["mineruBatchId"] = mineru_batch_id
        payload_json["mineruDataId"] = article.id
        job = await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=search_session.id,
            dedupe_key=f"ingest:{article.id}",
            payload_json=payload_json,
            created_at=now,
        )
        jobs.append(job)

    await session.commit()
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    meta = {
        "queuedCount": len(queued_batch_items),
        "failedCount": len(failed_batch_items),
    }
    if failed_batch_items:
        meta["failedReason"] = "mineru_batch_submit_partial_failed"
        meta["failedArticleIds"] = [article.id for article, _url, _error in failed_batch_items]
        return success_response(
            item=item,
            message="部分来源已成功入队，少量条目提交解析任务失败。",
            meta=meta,
        )
    return success_response(item=item, meta=meta)


# ── Import RSS entries (async) ────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/sources/import-rss")
async def import_rss_entries_endpoint(
    notebook_id: str,
    payload: ImportRssEntriesRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    notebook = await notebooks_repo.get_notebook(
        session, user_id=current_user.id, notebook_id=notebook_id,
    )
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    now = datetime.now(UTC)
    existing_articles = await notebooks_repo.list_articles_by_notebook(
        session,
        user_id=current_user.id,
        notebook_id=notebook_id,
    )
    existing_dedupe_keys = {article.dedupe_key for article in existing_articles if article.dedupe_key}

    jobs = []
    imported_entry_ids: list[int] = []
    imported_count = 0
    skipped_duplicate = 0

    for entry_id in payload.entryIds:
        entry = await feeds_service.get_entry_for_import(session, user=current_user, entry_id=entry_id)
        if not isinstance(entry, dict):
            continue

        raw_feed_id = entry.get("feed_id") or (entry.get("feed") or {}).get("id")
        try:
            miniflux_feed_id = int(raw_feed_id)
        except (TypeError, ValueError):
            miniflux_feed_id = 0

        raw_hash = str(entry.get("hash") or "").strip()
        if not raw_hash:
            dedupe_seed = f"{entry.get('url') or ''}|{entry.get('title') or ''}|{entry_id}"
            raw_hash = hashlib.sha256(dedupe_seed.encode("utf-8")).hexdigest()
        dedupe_key = f"rss:{miniflux_feed_id}:{raw_hash}"
        if dedupe_key in existing_dedupe_keys:
            skipped_duplicate += 1
            continue

        local_feed = None
        if miniflux_feed_id > 0:
            local_feed = await feeds_service.ensure_local_feed_by_miniflux_id(
                session,
                user=current_user,
                miniflux_feed_id=miniflux_feed_id,
            )

        title = str(entry.get("title") or "").strip() or f"RSS 文章 {entry_id}"
        source_url = str(entry.get("url") or "").strip() or None
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="rss_entry",
            dedupe_key=dedupe_key,
            title=title,
            source_url=source_url,
            author=(entry.get("author") or None),
            published_at=_parse_iso_datetime(entry.get("published_at") or entry.get("created_at")),
            preview_markdown=_build_rss_preview_markdown(
                title=title,
                url=source_url,
                content_html=entry.get("content"),
            ),
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
            rss_feed_id=local_feed.id if local_feed else None,
            rss_entry_id=entry_id,
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
        imported_entry_ids.append(entry_id)
        imported_count += 1
        existing_dedupe_keys.add(dedupe_key)

    if imported_count == 0:
        item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
        return success_response(
            item=item,
            message="选中的 RSS 文章已存在，无需重复导入",
            meta={"importedCount": 0, "skippedDuplicate": skipped_duplicate},
        )

    await session.commit()
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()

    if imported_entry_ids:
        try:
            await feeds_service.mark_entries_as_read(session, user=current_user, entry_ids=imported_entry_ids)
        except Exception:
            pass

    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(
        item=item,
        meta={"importedCount": imported_count, "skippedDuplicate": skipped_duplicate},
    )


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
        normalized_content = (payload.content or "").strip()
        if not normalized_content:
            raise AppError(422, "请输入文字内容", code="content_required")
        title = await _resolve_manual_source_title(
            source_type="text",
            provided_title=payload.title,
            content=normalized_content,
        )
        dedupe_key = f"text:{hashlib.sha256(normalized_content.encode()).hexdigest()}"
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="text",
            dedupe_key=dedupe_key,
            title=title,
            raw_text_input=normalized_content,
            preview_markdown=f"# {title}\n\n{normalized_content[:200]}...",
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
    elif payload.sourceType == "web":
        normalized_url = (payload.url or "").strip()
        if not normalized_url:
            raise AppError(422, "请输入网站链接", code="url_required")
        title = await _resolve_manual_source_title(
            source_type="web",
            provided_title=payload.title,
            url=normalized_url,
        )
        dedupe_key = f"url:{hashlib.sha256(normalized_url.encode()).hexdigest()}"
        article = Article(
            user_id=current_user.id,
            notebook_id=notebook_id,
            input_type="url",
            dedupe_key=dedupe_key,
            title=title,
            source_url=normalized_url,
            preview_markdown=f"# {title}\n\n来源链接：{normalized_url}\n\n等待解析中。",
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


@router.post("/notebooks/{notebook_id}/articles/{article_id}/retry")
async def retry_article_endpoint(
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
        raise AppError(404, "未找到对应文章", code="article_not_found")

    now = datetime.now(UTC)
    article.parse_status = "queued"
    article.parse_error_tag = None
    article.parse_error_message = None
    article.chunk_status = "not_started"
    article.index_status = "not_started"

    job = await jobs_repo.create_article_ingest_job(
        session,
        article_id=article.id,
        search_session_id=None,
        dedupe_key=f"retry-ingest:{article.id}:{int(now.timestamp())}",
        payload_json={"articleId": article.id},
        created_at=now,
    )
    await jobs_repo.mark_dead_letter_replayed_for_article(
        session,
        article_id=article.id,
        replay_job_id=job.id,
    )
    await session.commit()
    await job_publisher.publish_jobs(session, [job])
    await session.commit()
    await invalidate_notebook_detail_cache(user_id=current_user.id, notebook_id=notebook_id)
    item = await get_notebook_detail(session, user_id=current_user.id, notebook_id=notebook_id)
    return success_response(item=item)
