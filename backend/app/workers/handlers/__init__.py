"""Worker handlers for async job processing.

Handles article_ingest jobs. The worker picks up jobs from the Kafka
queue (or inline fallback) and runs the ingest pipeline.
Search is always synchronous – no search worker needed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import delete, select

import structlog

from app.core.config import get_settings
from app.infra.db.session import get_session_manager
from app.infra.telemetry.metrics import observe_mq_job_skip
from app.modules.ingest.types import IngestInput, InputType
from app.modules.ingest.service import build_article_chunk_rows, build_article_fields, ingest
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks import repo as notebooks_repo
from app.modules.notebooks.models import Article, ArticleChunk
from app.modules.notebooks.service import invalidate_notebook_detail_cache

logger = structlog.get_logger(__name__)

_TERMINAL_STATES = frozenset({"succeeded", "dead"})

JobProcessor = Callable[[str], Awaitable[None]]


async def _load_existing_dedupe_keys(session, *, notebook_id: str, article_id: str) -> set[str]:
    result = await session.execute(
        select(Article.dedupe_key).where(
            Article.notebook_id == notebook_id,
            Article.id != article_id,
        )
    )
    return {key for key in result.scalars().all() if key}


async def _replace_article_chunks(
    session,
    *,
    article_id: str,
    chunk_rows: list[dict],
) -> None:
    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id == article_id))
    for row in chunk_rows:
        session.add(ArticleChunk(article_id=article_id, **row))
    await session.flush()


async def process_article_ingest(job_id: str) -> None:
    """Execute the ingest pipeline for a queued article."""

    async for session in get_session_manager().session():
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            logger.warning("worker.article_ingest.job_not_found", job_id=job_id)
            return

        if job.status in _TERMINAL_STATES:
            logger.info("worker.article_ingest.skip_terminal", job_id=job_id, status=job.status)
            observe_mq_job_skip(job_type=job.job_type, reason=job.status)
            return

        if job.status == "running" and job.started_at:
            lease_ms = get_settings().kafka_max_poll_interval_ms
            elapsed = (datetime.now(UTC) - job.started_at).total_seconds()
            if elapsed < lease_ms / 1000:
                logger.info("worker.article_ingest.skip_running", job_id=job_id, elapsed_s=round(elapsed))
                observe_mq_job_skip(job_type=job.job_type, reason="running_lease_active")
                return

        await jobs_repo.mark_job_running(job)
        await session.commit()

        payload = job.payload_json or {}
        article_id = payload.get("articleId") or job.article_id
        if not article_id:
            await jobs_repo.mark_job_failed(job, error="missing articleId")
            await session.commit()
            return

        article = await notebooks_repo.get_article_by_id(session, article_id=article_id)
        if article is None:
            await jobs_repo.mark_job_failed(job, error="article not found")
            await session.commit()
            return

        try:
            try:
                input_type = InputType(article.input_type)
            except ValueError:
                input_type = InputType.URL

            existing_dedupe_keys = await _load_existing_dedupe_keys(
                session,
                notebook_id=article.notebook_id,
                article_id=article.id,
            )
            notebook = await notebooks_repo.get_notebook(session, user_id=article.user_id, notebook_id=article.notebook_id)
            ingest_input = IngestInput(
                input_type=input_type,
                notebook_id=article.notebook_id,
                user_id=article.user_id,
                title=article.title,
                notebook_title=notebook.title if notebook else '',
                source_url=article.source_url,
                file_name=article.file_name,
                file_mime=article.file_mime,
                raw_text=article.raw_text_input,
                author=article.author,
                published_at=article.published_at,
                description=article.preview_markdown,
            )

            if article.file_storage_key:
                from app.infra.storage.file_store import load_file_bytes
                ingest_input.file_bytes = load_file_bytes(article.file_storage_key)

            result = await ingest(
                session,
                ingest_input=ingest_input,
                article_id=article.id,
                existing_dedupe_keys=existing_dedupe_keys,
                mineru_batch_id=payload.get("mineruBatchId"),
                mineru_data_id=payload.get("mineruDataId"),
            )

            if result.is_duplicate:
                article.parse_status = "failed"
                article.parse_error_tag = "duplicate"
                article.parse_error_message = "该来源与当前笔记本中的已有文章重复，已跳过解析。"
                article.chunk_status = "failed"
                article.index_status = "failed"
            elif result.clean_markdown:
                fields = build_article_fields(result)
                for key, value in fields.items():
                    if hasattr(article, key):
                        setattr(article, key, value)
                chunk_rows = build_article_chunk_rows(result)
                await _replace_article_chunks(
                    session,
                    article_id=article.id,
                    chunk_rows=chunk_rows,
                )
                article.chunk_status = "completed" if chunk_rows else "failed"
                article.index_status = "completed" if chunk_rows else "failed"
                # 补写 article_vector
                await _try_embed_article_vector(article)
            else:
                article.parse_status = "failed"
                article.parse_error_tag = "no_content"
                article.parse_error_message = "解析未生成可用正文。"
                article.chunk_status = "failed"
                article.index_status = "failed"

            await jobs_repo.mark_job_succeeded(job)
            await session.commit()
            await invalidate_notebook_detail_cache(
                user_id=article.user_id,
                notebook_id=article.notebook_id,
            )
            logger.info(
                "worker.article_ingest.completed",
                article_id=article_id,
                job_id=job_id,
            )
        except Exception as exc:
            await session.rollback()
            job = await jobs_repo.get_job(session, job_id) or job
            await jobs_repo.mark_job_failed(job, error=str(exc)[:500])
            article = await notebooks_repo.get_article_by_id(session, article_id=article_id)
            if article:
                article.parse_status = "failed"
                article.parse_error_message = str(exc)[:500]
            await session.commit()
            logger.exception(
                "worker.article_ingest.failed",
                article_id=article_id,
                job_id=job_id,
            )


async def _try_embed_article_vector(article: Article) -> None:
    """对 article_retrieval_text 做 embedding 写入 article_vector。"""
    text = article.article_retrieval_text
    if not text:
        return
    try:
        from app.modules.settings.runtime import resolve_embedding_runtime_config
        from app.infra.ai.embedder import Embedder

        runtime_config = resolve_embedding_runtime_config(None)
        embedder = Embedder(runtime_config)
        if not embedder.is_configured:
            return
        vectors = await embedder.embed_texts([text[:4000]])
        if vectors and vectors[0]:
            article.article_vector = vectors[0]
    except Exception as exc:
        logger.debug("worker.embed_article_vector_failed", error=str(exc)[:200])


def _build_job_handler(*, job_type: str, log_event: str, processor: JobProcessor):
    async def _handler(payload: dict) -> None:
        logger.info(log_event, payload=payload)
        await processor(payload["jobId"])
    return _handler


handle_article_ingest = _build_job_handler(
    job_type="article_ingest",
    log_event="worker.article_ingest.received",
    processor=process_article_ingest,
)

__all__ = ["handle_article_ingest"]
