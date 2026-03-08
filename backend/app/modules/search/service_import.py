from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.ingest.service import IngestDraft, ingest_draft
from app.modules.notebooks import service as notebooks_service
from app.modules.search import repo_search


async def import_results(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    search_session_id: str,
    search_result_ids: list[str],
) -> dict:
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

    for search_result in search_results:
        await ingest_draft(
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

    await session.commit()
    return await notebooks_service.get_notebook_detail(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
    )
