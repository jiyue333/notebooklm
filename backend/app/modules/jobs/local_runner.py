from __future__ import annotations

from app.api.errors import AppError


async def run_job_inline(job_id: str, *, job_type: str) -> None:
    if job_type == "article_ingest":
        from app.modules.ingest.worker_handler import process_article_ingest

        await process_article_ingest(job_id)
        return
    if job_type == "article_reindex":
        from app.modules.ingest.worker_handler import process_article_reindex

        await process_article_reindex(job_id)
        return
    if job_type == "search_deep":
        from app.modules.ingest.worker_handler import process_search_deep

        await process_search_deep(job_id)
        return
    raise AppError(422, f"unsupported inline job type: {job_type}", code="unsupported_job_type")
