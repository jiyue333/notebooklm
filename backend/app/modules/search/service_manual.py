from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.ingest.parsers.markitdown_parser import convert_file_to_markdown
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.models import Article
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks import service as notebooks_service
from app.modules.search import repo_article
from app.modules.search.file_storage import build_storage_key, ensure_parent_dir, resolve_storage_path
from app.modules.search.markdown_utils import (
    build_web_placeholder,
    compute_content_hash,
    decode_text_bytes,
    extract_toc,
    normalize_text_to_markdown,
)


async def create_source(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    source_type: str,
    url: str | None = None,
    title: str | None = None,
    content: str | None = None,
) -> dict:
    notebook = await notebooks_repo.get_notebook(session, user_id=user.id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    now = datetime.now(UTC)
    if source_type == "text":
        normalized_title = (title or "粘贴文字来源").strip()
        normalized_markdown = normalize_text_to_markdown(
            title=normalized_title,
            content=content or "",
        )
        article = Article(
            user_id=user.id,
            notebook_id=notebook_id,
            input_type="text",
            dedupe_key=sha256(normalized_markdown.encode("utf-8")).hexdigest(),
            source_title_raw=normalized_title,
            raw_text_input=content or "",
            title=normalized_title,
            preview_markdown=normalized_markdown,
            clean_markdown=normalized_markdown,
            toc_json=extract_toc(normalized_markdown),
            content_hash=compute_content_hash(normalized_markdown),
            parse_status="ready",
            chunk_status="not_started",
            index_status="not_started",
            ingested_at=now,
        )
        await repo_article.create_article(session, article)
        await session.commit()
        return await notebooks_service.get_notebook_detail(session, user_id=user.id, notebook_id=notebook_id)

    if source_type != "web":
        raise AppError(422, "不支持的来源类型", code="invalid_source_type")

    if not url:
        raise AppError(422, "请输入网站链接", code="url_required")

    normalized_title = (title or url).strip()
    dedupe_key = sha256(url.strip().encode("utf-8")).hexdigest()
    existing = await repo_article.list_existing_dedupe_keys(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        dedupe_keys=[dedupe_key],
    )
    if not existing:
        article = Article(
            user_id=user.id,
            notebook_id=notebook_id,
            input_type="url",
            source_url=url.strip(),
            normalized_url=url.strip(),
            dedupe_key=dedupe_key,
            source_title_raw=normalized_title,
            title=normalized_title,
            preview_markdown=build_web_placeholder(title=normalized_title, url=url.strip()),
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
        await repo_article.create_article(session, article)
        await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=None,
            dedupe_key=f"article_ingest:{article.id}",
            payload_json={"articleId": article.id, "inputType": article.input_type},
            created_at=now,
        )
        await session.commit()

    return await notebooks_service.get_notebook_detail(session, user_id=user.id, notebook_id=notebook_id)


async def upload_files(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    files: list[UploadFile],
) -> dict:
    notebook = await notebooks_repo.get_notebook(session, user_id=user.id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    now = datetime.now(UTC)
    for upload in files:
        data = await upload.read()
        if not data:
            continue

        file_hash = sha256(data).hexdigest()
        existing = await repo_article.list_existing_dedupe_keys(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            dedupe_keys=[file_hash],
        )
        if existing:
            continue

        suffix = Path(upload.filename or "").suffix.lower()
        mime = upload.content_type or _guess_mime_from_suffix(suffix)
        title = (upload.filename or "未命名文件").strip()

        if suffix in {".md", ".txt"}:
            text = decode_text_bytes(data)
            markdown = text if suffix == ".md" else normalize_text_to_markdown(title=title, content=text)
            article = Article(
                user_id=user.id,
                notebook_id=notebook_id,
                input_type="file",
                dedupe_key=file_hash,
                file_name=upload.filename,
                file_ext=suffix.lstrip(".") or None,
                file_mime=mime,
                file_size=len(data),
                title=title,
                preview_markdown=markdown,
                clean_markdown=markdown,
                toc_json=extract_toc(markdown),
                content_hash=compute_content_hash(markdown),
                parse_status="ready",
                chunk_status="not_started",
                index_status="not_started",
                ingested_at=now,
            )
            await repo_article.create_article(session, article)
            continue

        article = Article(
            user_id=user.id,
            notebook_id=notebook_id,
            input_type="file",
            dedupe_key=file_hash,
            file_name=upload.filename,
            file_ext=suffix.lstrip(".") or None,
            file_mime=mime,
            file_size=len(data),
            title=title,
            preview_markdown=f"# {title}\n\n文件已上传，正在解析内容。\n",
            parse_status="queued",
            chunk_status="not_started",
            index_status="not_started",
        )
        await repo_article.create_article(session, article)

        storage_key = build_storage_key(
            notebook_id=notebook_id,
            article_id=article.id,
            filename=upload.filename or article.id,
        )
        absolute_path = ensure_parent_dir(storage_key)
        absolute_path.write_bytes(data)
        article.file_storage_key = storage_key

        markdown_result = convert_file_to_markdown(absolute_path)
        if markdown_result is not None:
            markdown, parser_name = markdown_result
            if markdown:
                article.clean_markdown = markdown
                article.content_hash = compute_content_hash(markdown)
                article.toc_json = extract_toc(markdown)
                article.parser_name = parser_name
                article.parse_status = "ready"
                if not article.preview_markdown:
                    article.preview_markdown = markdown[:2000]

        await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=None,
            dedupe_key=f"article_ingest:{article.id}",
            payload_json={"articleId": article.id, "inputType": article.input_type},
            created_at=now,
        )

    await session.commit()
    return await notebooks_service.get_notebook_detail(session, user_id=user.id, notebook_id=notebook_id)


def resolve_article_file_path(article: Article) -> Path:
    if not article.file_storage_key:
        raise AppError(404, "文章没有原始文件", code="article_file_not_found")
    return resolve_storage_path(article.file_storage_key)


def _guess_mime_from_suffix(suffix: str) -> str:
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".txt", ".md"}:
        return "text/plain"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if suffix == ".doc":
        return "application/msword"
    return "application/octet-stream"
