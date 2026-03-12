from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_source_import
from app.modules.ingest.articles.draft import IngestDraft
from app.modules.ingest.articles.service import ingest_draft
from app.modules.jobs import publisher as job_publisher
from app.modules.notebooks.service import invalidate_notebook_detail_cache
from app.modules.search.sessions import repo as repo_search


async def import_results(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    search_session_id: str,
    search_result_ids: list[str],
) -> dict:
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    search_session = await repo_search.get_search_session(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        search_session_id=search_session_id,
    )
    if search_session is None:
        raise AppError(404, "未找到对应搜索会话", code="search_session_not_found")
    if search_session.status != "completed":
        raise AppError(409, "搜索结果尚未准备完成", code="search_session_not_ready")

    unique_result_ids = list(dict.fromkeys(search_result_ids))
    search_results = await repo_search.list_search_results_by_ids(
        session,
        search_session_id=search_session.id,
        result_ids=unique_result_ids,
    )
    if len(search_results) != len(unique_result_ids):
        raise AppError(422, "部分搜索结果不存在或不属于当前搜索会话", code="invalid_search_result_ids")

    jobs = []
    imported_count = 0
    skipped_count = 0
    for search_result in search_results:
        article, job = await ingest_draft(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            draft=IngestDraft(
                input_type="search_result",
                title=search_result.title,
                preview_markdown=search_result.preview_markdown or search_result.description,
                source_url=search_result.raw_url,
                normalized_url=search_result.canonical_url,
                origin_search_session_id=search_session.id,
                origin_search_result_id=search_result.id,
                author=search_result.author,
                published_at=search_result.published_at,
                source_title_raw=search_result.title,
            ),
        )
        if article is None:
            skipped_count += 1
            continue
        imported_count += 1
        if job is not None:
            jobs.append(job)

    if imported_count:
        observe_source_import(source_type="search_result", result="imported", count=imported_count)
    if skipped_count:
        observe_source_import(source_type="search_result", result="skipped", count=skipped_count)
    await session.commit()
    if imported_count or skipped_count:
        await invalidate_notebook_detail_cache(user_id=user.id, notebook_id=notebook_id)
    if jobs:
        await job_publisher.publish_jobs(session, jobs)
        await session.commit()
    return {"importedCount": imported_count, "skippedCount": skipped_count}
