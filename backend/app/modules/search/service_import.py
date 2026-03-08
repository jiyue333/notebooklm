from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import service as notebooks_service
from app.modules.search import repo_article, repo_search


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

    existing_dedupe_keys = await repo_article.list_existing_dedupe_keys(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        dedupe_keys=[result.url_hash for result in search_results],
    )

    now = datetime.now(UTC)
    for search_result in search_results:
        if search_result.url_hash in existing_dedupe_keys:
            continue

        article = await repo_article.create_search_result_article(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            search_session_id=search_session.id,
            search_result=search_result,
            created_at=now,
        )
        await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=search_session.id,
            dedupe_key=f"article_ingest:{article.id}",
            payload_json={
                "articleId": article.id,
                "inputType": article.input_type,
                "originSearchResultId": search_result.id,
            },
            created_at=now,
        )

    await session.commit()
    return await notebooks_service.get_notebook_detail(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
    )
