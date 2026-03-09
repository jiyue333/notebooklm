from __future__ import annotations

from datetime import UTC, datetime

from app.api.errors import AppError
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
from app.modules.search.file_storage import resolve_storage_path
from app.modules.search.service_search import execute_search
from app.modules.settings.crypto import get_credential_crypto


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
            return

        user = await get_user_by_id(session, article.user_id)
        markdown = article.clean_markdown
        parser_name = article.parser_name

        try:
            if not markdown and article.input_type in {"search_result", "url"} and article.source_url and user and user.exa_api_key_ciphertext:
                api_key = get_credential_crypto().decrypt(user.exa_api_key_ciphertext)
                markdown, parser_name = await fetch_markdown_with_exa(url=article.source_url, api_key=api_key)
                if not markdown:
                    markdown, parser_name = fetch_markdown_with_trafilatura(url=article.source_url)
            elif not markdown and article.input_type == "file" and article.file_storage_key:
                file_path = resolve_storage_path(article.file_storage_key)
                if file_path.exists():
                    parsed = parse_file_content(
                        file_name=article.file_name,
                        file_path=file_path,
                        file_bytes=file_path.read_bytes(),
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
                await _index_article_content(session, article)
                await jobs_repo.mark_job_succeeded(job)
            else:
                article.parse_status = "failed"
                article.parse_error_tag = "parse_empty"
                article.parse_error_message = "No markdown content extracted"
                await jobs_repo.mark_job_failed(job, error="No markdown content extracted")
            await session.commit()
        except Exception as exc:
            article.parse_status = "failed"
            article.parse_error_tag = "ingest_failed"
            article.parse_error_message = str(exc)
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            raise
        return


async def process_search_deep(job_id: str) -> None:
    async for session in get_session_manager().session():
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            raise AppError(404, "job not found", code="job_not_found")
        await jobs_repo.mark_job_running(job)
        await session.commit()
        try:
            await execute_search(job.search_session_id or "")
            await jobs_repo.mark_job_succeeded(job)
            await session.commit()
        except Exception as exc:
            await jobs_repo.mark_job_failed(job, error=str(exc))
            await session.commit()
            raise
        return
