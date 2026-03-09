from __future__ import annotations

from datetime import UTC, datetime

from app.api.errors import AppError
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_ingest_fallback, observe_ingest_parse, observe_job
from app.infra.db.session import get_session_manager
from app.modules.auth.repo import get_user_by_id
from app.modules.ingest.markdown_cleaner import clean_markdown
from app.modules.ingest.parser_router import parse_file_content
from app.modules.ingest.quality_scorer import score_markdown
from app.modules.ingest.service import _apply_parsed_content, _index_article_content
from app.modules.ingest.toc_extractor import extract_toc_items
from app.modules.ingest.parsers.exa_contents_parser import fetch_markdown_with_exa
from app.modules.ingest.parsers.llm_markdown_fallback import fallback_to_markdown
from app.modules.ingest.parsers.trafilatura_parser import fetch_markdown_with_trafilatura
from app.modules.jobs import repo as jobs_repo
from app.modules.search import repo_article
from app.modules.search.file_storage import (
    load_file_bytes,
    materialize_stored_file_for_parser,
    stored_file_exists,
)
from app.modules.search.service_search import execute_search
from app.modules.settings.runtime import resolve_search_api_key


async def process_article_ingest(job_id: str) -> None:
    async for session in get_session_manager().session():
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

        try:
            search_api_key, _key_source = resolve_search_api_key(user) if user is not None else (None, "missing")
            if not markdown and article.input_type in {"search_result", "url"} and article.source_url:
                if search_api_key:
                    markdown, parser_name = await fetch_markdown_with_exa(url=article.source_url, api_key=search_api_key)
                    if markdown:
                        observe_ingest_fallback(fallback_type="exa_contents")
                if not markdown:
                    markdown, parser_name = fetch_markdown_with_trafilatura(url=article.source_url)
                    if markdown:
                        observe_ingest_fallback(fallback_type="trafilatura")
            elif not markdown and article.input_type == "file" and article.file_storage_key:
                if stored_file_exists(article.file_storage_key):
                    file_bytes = load_file_bytes(article.file_storage_key)
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

            if markdown:
                markdown = clean_markdown(markdown)
                quality = score_markdown(markdown)
                article.parse_quality_score = quality.score
                if quality.needs_llm_fallback and user is not None:
                    fallback_markdown, fallback_parser = await fallback_to_markdown(
                        user=user,
                        title=article.title,
                        raw_text=markdown,
                    )
                    if fallback_markdown:
                        markdown = clean_markdown(fallback_markdown)
                        parser_name = fallback_parser

                _apply_parsed_content(article, markdown, parser_name, datetime.now(UTC))
                article.toc_json = extract_toc_items(markdown)
                if user is not None:
                    await _index_article_content(session, article, user=user)
                await jobs_repo.mark_job_succeeded(job)
                observe_ingest_parse(
                    input_type=article.input_type,
                    status="ready",
                    parser=parser_name or "unknown",
                )
                observe_job(job_type=job.job_type, status="succeeded")
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
        except Exception as exc:
            article.parse_status = "failed"
            article.parse_error_tag = "ingest_failed"
            article.parse_error_message = str(exc)
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            observe_ingest_parse(
                input_type=article.input_type,
                status="failed",
                parser=parser_name or "unknown",
                error_tag="ingest_failed",
            )
            observe_job(job_type=job.job_type, status="failed")
            raise
        return


async def process_article_reindex(job_id: str) -> None:
    async for session in get_session_manager().session():
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
            await _index_article_content(session, article, user=user)
            await jobs_repo.mark_job_succeeded(job)
            await session.commit()
            observe_job(job_type=job.job_type, status="succeeded")
        except Exception as exc:
            article.index_status = "failed"
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            observe_job(job_type=job.job_type, status="failed")
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
