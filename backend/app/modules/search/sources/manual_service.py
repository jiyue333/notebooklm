from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.storage.mime import guess_mime_from_suffix
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_source_import
from app.modules.ingest.articles.draft import IngestDraft
from app.modules.ingest.articles.service import ingest_draft
from app.modules.jobs import publisher as job_publisher
from app.modules.notebooks import repo as notebooks_repo
from app.modules.search.sources.drafts import UploadedSourceFile
from app.modules.search.markdown_utils import (
    build_web_placeholder,
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
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        source_type=source_type,
    )
    notebook = await notebooks_repo.get_notebook(session, user_id=user.id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    if source_type == "text":
        normalized_title = (title or "粘贴文字来源").strip()
        await ingest_draft(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            draft=IngestDraft(
                input_type="text",
                title=normalized_title,
                raw_text_input=content or "",
                source_title_raw=normalized_title,
            ),
        )
        observe_source_import(source_type="text", result="imported")
        await session.commit()
        return {"importedCount": 1, "skippedCount": 0}

    if source_type != "web":
        raise AppError(422, "不支持的来源类型", code="invalid_source_type")

    if not url:
        raise AppError(422, "请输入网站链接", code="url_required")

    normalized_title = (title or url).strip()
    _article, job = await ingest_draft(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        draft=IngestDraft(
            input_type="url",
            title=normalized_title,
            preview_markdown=build_web_placeholder(title=normalized_title, url=url.strip()),
            source_url=url.strip(),
            normalized_url=url.strip(),
            source_title_raw=normalized_title,
        ),
    )
    observe_source_import(source_type="url", result="imported" if _article is not None else "skipped")
    await session.commit()
    if job is not None:
        await job_publisher.publish_jobs(session, [job])
        await session.commit()

    return {"importedCount": 1 if _article is not None else 0, "skippedCount": 0 if _article is not None else 1}


async def upload_files(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    files: list[UploadedSourceFile],
) -> dict:
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        source_type="file",
    )
    notebook = await notebooks_repo.get_notebook(session, user_id=user.id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    jobs = []
    imported_count = 0
    skipped_count = 0
    for upload in files:
        if not upload.data:
            continue

        article, job = await ingest_draft(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            draft=IngestDraft(
                input_type="file",
                title=(upload.file_name or "未命名文件").strip(),
                preview_markdown=f"# {(upload.file_name or '未命名文件').strip()}\n\n文件已上传，正在解析内容。\n",
                file_name=upload.file_name,
                file_mime=upload.content_type or guess_mime_from_suffix(upload.file_name),
                file_bytes=upload.data,
                source_title_raw=upload.file_name or "未命名文件",
            ),
        )
        if article is None:
            skipped_count += 1
            continue
        imported_count += 1
        if job is not None:
            jobs.append(job)

    if imported_count:
        observe_source_import(source_type="file", result="imported", count=imported_count)
    if skipped_count:
        observe_source_import(source_type="file", result="skipped", count=skipped_count)
    await session.commit()
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()
    return {"importedCount": imported_count, "skippedCount": skipped_count}
