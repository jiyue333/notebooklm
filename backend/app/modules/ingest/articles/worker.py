from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

import structlog

from app.api.errors import AppError
from app.infra.telemetry.context import bind_observability_context
from app.infra.storage.file_store import (
    load_file_bytes,
    materialize_stored_file_for_parser,
    stored_file_exists,
)
from app.infra.telemetry.metrics import observe_ingest_fallback, observe_ingest_parse, observe_job
from app.infra.db.session import get_session_manager
from app.modules.auth.repo import get_user_by_id
from app.modules.ingest.articles.content import apply_parsed_content, record_article_ready
from app.modules.ingest.indexing.pipeline import index_article_content
from app.modules.ingest.parsers.exa_contents_parser import fetch_markdown_with_exa
from app.modules.ingest.parsers.llm_markdown_fallback import fallback_to_markdown
from app.modules.ingest.parsers.router import parse_file_content
from app.modules.ingest.parsers.trafilatura_parser import fetch_markdown_with_trafilatura
from app.modules.ingest.quality.markdown_cleaner import clean_markdown
from app.modules.ingest.quality.quality_scorer import score_markdown
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.service import invalidate_notebook_detail_cache
from app.modules.search.articles import repo as repo_article
from app.modules.search.sessions.service import execute_search
from app.modules.settings.runtime import resolve_search_api_key

logger = structlog.get_logger(__name__)


async def process_article_ingest(job_id: str) -> None:
    async for session in get_session_manager().session():
        total_started = perf_counter()
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            raise AppError(404, "job not found", code="job_not_found")
        await jobs_repo.mark_job_running(job)
        await session.commit()

        article = await repo_article.get_article_by_id(session, article_id=job.article_id)
        if article is None:
            await jobs_repo.mark_job_failed(job, error="article not found")
            await session.commit()
            observe_job(job_type=job.job_type, status="failed")
            return

        user = await get_user_by_id(session, article.user_id)
        bind_observability_context(
            user_id=article.user_id,
            notebook_id=article.notebook_id,
            article_id=article.id,
            job_id=job.id,
        )
        markdown = article.clean_markdown
        parser_name = article.parser_name
        parsed_content_committed = False
        content_was_ready = article.parse_status == "ready" and bool((article.clean_markdown or "").strip())
        fetch_strategy = "existing_markdown" if markdown else "none"
        fetch_duration_ms = 0.0
        file_parse_ms = 0.0
        clean_ms = 0.0
        quality_ms = 0.0
        llm_fallback_ms = 0.0
        llm_fallback_applied = False
        parse_commit_ms = 0.0
        index_stats: dict[str, float | int | str] = {}

        try:
            search_api_key, _key_source = resolve_search_api_key(user) if user is not None else (None, "missing")
            if not markdown and article.input_type in {"search_result", "url"} and article.source_url:
                if search_api_key:
                    fetch_started = perf_counter()
                    markdown, parser_name = await fetch_markdown_with_exa(url=article.source_url, api_key=search_api_key)
                    fetch_duration_ms = round((perf_counter() - fetch_started) * 1000, 2)
                    fetch_strategy = "exa_contents"
                    if markdown:
                        observe_ingest_fallback(fallback_type="exa_contents")
                if not markdown:
                    fetch_started = perf_counter()
                    markdown, parser_name = fetch_markdown_with_trafilatura(url=article.source_url)
                    fetch_duration_ms = round((perf_counter() - fetch_started) * 1000, 2)
                    fetch_strategy = "trafilatura"
                    if markdown:
                        observe_ingest_fallback(fallback_type="trafilatura")
            elif not markdown and article.input_type == "file" and article.file_storage_key:
                if stored_file_exists(article.file_storage_key):
                    file_bytes = load_file_bytes(article.file_storage_key)
                    parse_started = perf_counter()
                    with materialize_stored_file_for_parser(
                        storage_key=article.file_storage_key,
                        file_name=article.file_name,
                    ) as file_path:
                        parsed = parse_file_content(
                            file_name=article.file_name,
                            file_path=file_path,
                            file_bytes=file_bytes,
                        )
                    markdown = parsed.markdown
                    parser_name = parsed.parser_name
                    file_parse_ms = round((perf_counter() - parse_started) * 1000, 2)
                    fetch_strategy = "file_parser"

            if markdown:
                clean_started = perf_counter()
                markdown = clean_markdown(markdown)
                clean_ms = round((perf_counter() - clean_started) * 1000, 2)
                quality_started = perf_counter()
                quality = score_markdown(markdown)
                quality_ms = round((perf_counter() - quality_started) * 1000, 2)
                article.parse_quality_score = quality.score
                if quality.needs_llm_fallback and user is not None:
                    fallback_started = perf_counter()
                    fallback_markdown, fallback_parser = await fallback_to_markdown(
                        user=user,
                        title=article.title,
                        raw_text=markdown,
                    )
                    llm_fallback_ms = round((perf_counter() - fallback_started) * 1000, 2)
                    if fallback_markdown:
                        markdown = clean_markdown(fallback_markdown)
                        parser_name = fallback_parser
                        llm_fallback_applied = True

                commit_started = perf_counter()
                apply_parsed_content(article, markdown, parser_name, datetime.now(UTC))
                article.chunk_status = "processing"
                article.index_status = "processing"
                await session.commit()
                await invalidate_notebook_detail_cache(
                    user_id=article.user_id,
                    notebook_id=article.notebook_id,
                )
                parse_commit_ms = round((perf_counter() - commit_started) * 1000, 2)
                parsed_content_committed = True
                if not content_was_ready:
                    record_article_ready(article)
                observe_ingest_parse(
                    input_type=article.input_type,
                    status="ready",
                    parser=parser_name or "unknown",
                )
                if user is not None:
                    index_stats = await index_article_content(session, article, user=user)
                else:
                    article.chunk_status = "not_started"
                    article.index_status = "not_started"
                    index_stats = {
                        "chunk_count": 0,
                        "chunking_ms": 0.0,
                        "embedding_ms": 0.0,
                        "persist_ms": 0.0,
                        "index_total_ms": 0.0,
                        "embedding_status": "skipped_no_user",
                    }
                await jobs_repo.mark_job_succeeded(job)
                observe_job(job_type=job.job_type, status="succeeded")
                await session.commit()
                await invalidate_notebook_detail_cache(
                    user_id=article.user_id,
                    notebook_id=article.notebook_id,
                )
                logger.info(
                    "ingest.article_completed",
                    article_id=article.id,
                    notebook_id=article.notebook_id,
                    job_id=job.id,
                    input_type=article.input_type,
                    parser=parser_name or "unknown",
                    fetch_strategy=fetch_strategy,
                    fetch_ms=fetch_duration_ms,
                    file_parse_ms=file_parse_ms,
                    clean_ms=clean_ms,
                    quality_ms=quality_ms,
                    quality_score=float(article.parse_quality_score or 0),
                    llm_fallback_ms=llm_fallback_ms,
                    llm_fallback_applied=llm_fallback_applied,
                    parse_commit_ms=parse_commit_ms,
                    total_ms=round((perf_counter() - total_started) * 1000, 2),
                    **index_stats,
                )
            else:
                article.parse_status = "failed"
                article.parse_error_tag = "parse_empty"
                article.parse_error_message = "No markdown content extracted"
                await jobs_repo.mark_job_failed(job, error="No markdown content extracted")
                observe_ingest_parse(
                    input_type=article.input_type,
                    status="failed",
                    parser=parser_name or "unknown",
                    error_tag="parse_empty",
                )
                observe_job(job_type=job.job_type, status="failed")
                await session.commit()
                await invalidate_notebook_detail_cache(
                    user_id=article.user_id,
                    notebook_id=article.notebook_id,
                )
                logger.warning(
                    "ingest.article_failed",
                    article_id=article.id,
                    notebook_id=article.notebook_id,
                    job_id=job.id,
                    input_type=article.input_type,
                    error_tag="parse_empty",
                    parser=parser_name or "unknown",
                    fetch_strategy=fetch_strategy,
                    fetch_ms=fetch_duration_ms,
                    file_parse_ms=file_parse_ms,
                    total_ms=round((perf_counter() - total_started) * 1000, 2),
                )
        except Exception as exc:
            if parsed_content_committed:
                article.chunk_status = "failed"
                article.index_status = "failed"
            else:
                article.parse_status = "failed"
                article.parse_error_tag = "ingest_failed"
                article.parse_error_message = str(exc)
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            await invalidate_notebook_detail_cache(
                user_id=article.user_id,
                notebook_id=article.notebook_id,
            )
            if not parsed_content_committed:
                observe_ingest_parse(
                    input_type=article.input_type,
                    status="failed",
                    parser=parser_name or "unknown",
                    error_tag="ingest_failed",
                )
            observe_job(job_type=job.job_type, status="failed")
            logger.exception(
                "ingest.article_failed",
                article_id=article.id,
                notebook_id=article.notebook_id,
                job_id=job.id,
                input_type=article.input_type,
                error_tag=article.parse_error_tag or "ingest_failed",
                parser=parser_name or "unknown",
                fetch_strategy=fetch_strategy,
                fetch_ms=fetch_duration_ms,
                file_parse_ms=file_parse_ms,
                clean_ms=clean_ms,
                quality_ms=quality_ms,
                llm_fallback_ms=llm_fallback_ms,
                parse_commit_ms=parse_commit_ms,
                total_ms=round((perf_counter() - total_started) * 1000, 2),
                error=str(exc),
                **index_stats,
            )
            raise
        return


async def process_article_reindex(job_id: str) -> None:
    async for session in get_session_manager().session():
        total_started = perf_counter()
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            raise AppError(404, "job not found", code="job_not_found")
        await jobs_repo.mark_job_running(job)
        await session.commit()

        article = await repo_article.get_article_by_id(session, article_id=job.article_id)
        if article is None:
            await jobs_repo.mark_job_failed(job, error="article not found")
            await session.commit()
            observe_job(job_type=job.job_type, status="failed")
            return

        user = await get_user_by_id(session, article.user_id)
        if user is None:
            await jobs_repo.mark_job_failed(job, error="user not found")
            await session.commit()
            observe_job(job_type=job.job_type, status="failed")
            return

        bind_observability_context(
            user_id=article.user_id,
            notebook_id=article.notebook_id,
            article_id=article.id,
            job_id=job.id,
        )
        try:
            if not article.clean_markdown:
                await jobs_repo.mark_job_failed(job, error="article clean markdown not ready")
                await session.commit()
                observe_job(job_type=job.job_type, status="failed")
                return

            article.index_status = "reindexing"
            index_stats = await index_article_content(session, article, user=user)
            await jobs_repo.mark_job_succeeded(job)
            await session.commit()
            await invalidate_notebook_detail_cache(
                user_id=article.user_id,
                notebook_id=article.notebook_id,
            )
            observe_job(job_type=job.job_type, status="succeeded")
            logger.info(
                "ingest.article_reindex_completed",
                article_id=article.id,
                notebook_id=article.notebook_id,
                job_id=job.id,
                input_type=article.input_type,
                total_ms=round((perf_counter() - total_started) * 1000, 2),
                **index_stats,
            )
        except Exception as exc:
            article.index_status = "failed"
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            await invalidate_notebook_detail_cache(
                user_id=article.user_id,
                notebook_id=article.notebook_id,
            )
            observe_job(job_type=job.job_type, status="failed")
            logger.exception(
                "ingest.article_reindex_failed",
                article_id=article.id,
                notebook_id=article.notebook_id,
                job_id=job.id,
                input_type=article.input_type,
                total_ms=round((perf_counter() - total_started) * 1000, 2),
                error=str(exc),
            )
            raise
        return


async def process_search_deep(job_id: str) -> None:
    async for session in get_session_manager().session():
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            raise AppError(404, "job not found", code="job_not_found")
        bind_observability_context(
            search_session_id=job.search_session_id,
            job_id=job.id,
        )
        await jobs_repo.mark_job_running(job)
        await session.commit()
        try:
            await execute_search(job.search_session_id or "")
            await jobs_repo.mark_job_succeeded(job)
            await session.commit()
            observe_job(job_type=job.job_type, status="succeeded")
        except Exception as exc:
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            observe_job(job_type=job.job_type, status="failed")
            raise
        return
