from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.storage.file_store import (
    build_storage_key,
    materialize_uploaded_file_for_parser,
    store_file_bytes,
)
from app.infra.storage.mime import is_image_mime
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import (
    observe_ingest_doc_type,
    observe_ingest_doc_type_quality_score,
    observe_ingest_doc_type_structure_score,
    observe_ingest_parse,
    observe_ingest_quality_score,
    observe_ingest_stage,
    observe_ingest_structure_score,
)
from app.infra.telemetry.tracing import start_span
from app.modules.auth.repo import get_user_by_id
from app.modules.ingest.articles.content import apply_parsed_content, record_article_ready
from app.modules.ingest.articles.dedupe import build_dedupe_key, extract_file_ext
from app.modules.ingest.articles.draft import IngestDraft
from app.modules.ingest.indexing.pipeline import index_article_content
from app.modules.ingest.indexing.retrieval_text_builder import build_article_retrieval_text
from app.modules.ingest.parsers.router import parse_file_content
from app.modules.ingest.quality.quality_scorer import score_markdown
from app.modules.jobs import repo as jobs_repo
from app.modules.jobs.models import Job
from app.modules.notebooks.models import Article
from app.modules.search.articles import repo as repo_article
from app.modules.search.markdown_utils import (
    build_image_markdown,
    build_web_placeholder,
    normalize_text_to_markdown,
)
from app.modules.tracker.document_types import classify_document_type


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)


async def ingest_draft(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    draft: IngestDraft,
) -> tuple[Article | None, Job | None]:
    started_at = perf_counter()
    now = datetime.now(UTC)
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise RuntimeError("user not found")
    bind_observability_context(
        user_id=user_id,
        notebook_id=notebook_id,
        input_type=draft.input_type,
    )
    dedupe_key = build_dedupe_key(draft)
    existing = await repo_article.list_existing_dedupe_keys(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        dedupe_keys=[dedupe_key],
    )
    if existing:
        return None, None

    article = Article(
        user_id=user_id,
        notebook_id=notebook_id,
        input_type=draft.input_type,
        origin_search_session_id=draft.origin_search_session_id,
        origin_search_result_id=draft.origin_search_result_id,
        source_url=draft.source_url,
        normalized_url=draft.normalized_url,
        dedupe_key=dedupe_key,
        source_title_raw=draft.source_title_raw or draft.title,
        raw_text_input=draft.raw_text_input,
        file_name=draft.file_name,
        file_mime=draft.file_mime,
        file_ext=extract_file_ext(draft.file_name),
        file_size=len(draft.file_bytes) if draft.file_bytes is not None else None,
        title=draft.title,
        author=draft.author,
        published_at=draft.published_at,
        preview_markdown=draft.preview_markdown,
        article_retrieval_text=build_article_retrieval_text(
            title=draft.title,
            preview_markdown=draft.preview_markdown,
        ) if draft.preview_markdown else draft.title.strip(),
        parse_status="queued",
        chunk_status="not_started",
        index_status="not_started",
    )
    await repo_article.create_article(session, article)

    if draft.file_bytes is not None and draft.file_name:
        storage_key = build_storage_key(
            notebook_id=notebook_id,
            article_id=article.id,
            filename=draft.file_name,
        )
        store_file_bytes(
            storage_key=storage_key,
            data=draft.file_bytes,
            content_type=draft.file_mime or "application/octet-stream",
        )
        article.file_storage_key = storage_key
        if is_image_mime(draft.file_mime):
            parse_started = perf_counter()
            markdown = build_image_markdown(
                title=draft.title,
                image_url=f"/api/notebooks/{notebook_id}/articles/{article.id}/file",
            )
            apply_parsed_content(article, markdown, "image_upload", now)
            quality = score_markdown(markdown)
            document_type = classify_document_type(
                input_type=draft.input_type,
                file_name=draft.file_name,
                file_mime=draft.file_mime,
                parser_name="image_upload",
                markdown=markdown,
                quality=quality,
            )
            article.parse_quality_score = quality.score
            observe_ingest_quality_score(input_type="file", score=float(quality.score))
            observe_ingest_doc_type_quality_score(doc_type=document_type, score=float(quality.score))
            for structure_type, structure_score in quality.structure_scores.items():
                observe_ingest_structure_score(
                    input_type="file",
                    structure_type=structure_type,
                    score=float(structure_score),
                )
                observe_ingest_doc_type_structure_score(
                    doc_type=document_type,
                    structure_type=structure_type,
                    score=float(structure_score),
                )
            observe_ingest_stage(
                stage="parse",
                input_type="file",
                status="success",
                duration_ms=_elapsed_ms(parse_started),
            )
            observe_ingest_parse(
                input_type="file",
                status="ready",
                parser="image_upload",
            )
            observe_ingest_doc_type(doc_type=document_type, status="ready")
            record_article_ready(article)
        else:
            parse_started = perf_counter()
            with start_span(
                "ingest.parse",
                attributes={
                    "input_type": draft.input_type,
                    "file_name": draft.file_name,
                },
            ):
                with materialize_uploaded_file_for_parser(
                    file_name=draft.file_name,
                    file_bytes=draft.file_bytes,
                ) as temp_path:
                    parsed = parse_file_content(
                        file_name=draft.file_name,
                        file_path=temp_path,
                        file_bytes=draft.file_bytes,
                    )
            apply_parsed_content(article, parsed.markdown, parsed.parser_name, now)
            if parsed.markdown:
                quality = score_markdown(parsed.markdown)
                document_type = classify_document_type(
                    input_type=draft.input_type,
                    file_name=draft.file_name,
                    file_mime=draft.file_mime,
                    parser_name=parsed.parser_name,
                    markdown=parsed.markdown,
                    quality=quality,
                )
                article.parse_quality_score = quality.score
                observe_ingest_quality_score(input_type="file", score=float(quality.score))
                observe_ingest_doc_type_quality_score(doc_type=document_type, score=float(quality.score))
                for structure_type, structure_score in quality.structure_scores.items():
                    observe_ingest_structure_score(
                        input_type="file",
                        structure_type=structure_type,
                        score=float(structure_score),
                    )
                    observe_ingest_doc_type_structure_score(
                        doc_type=document_type,
                        structure_type=structure_type,
                        score=float(structure_score),
                    )
                observe_ingest_stage(
                    stage="parse",
                    input_type="file",
                    status="success",
                    duration_ms=_elapsed_ms(parse_started),
                )
                observe_ingest_parse(
                    input_type="file",
                    status="ready",
                    parser=parsed.parser_name or "unknown",
                )
                observe_ingest_doc_type(doc_type=document_type, status="ready")
                record_article_ready(article)
            else:
                observe_ingest_doc_type(
                    doc_type=classify_document_type(
                        input_type=draft.input_type,
                        file_name=draft.file_name,
                        file_mime=draft.file_mime,
                    ),
                    status="empty",
                )
                observe_ingest_stage(
                    stage="parse",
                    input_type="file",
                    status="empty",
                    duration_ms=_elapsed_ms(parse_started),
                )
    elif draft.input_type == "text":
        parse_started = perf_counter()
        with start_span(
            "ingest.parse",
            attributes={
                "input_type": draft.input_type,
            },
        ):
            markdown = normalize_text_to_markdown(title=draft.title, content=draft.raw_text_input or "")
        apply_parsed_content(article, markdown, "raw_text", now)
        quality = score_markdown(markdown)
        document_type = classify_document_type(
            input_type=draft.input_type,
            markdown=markdown,
            parser_name="raw_text",
            quality=quality,
        )
        article.parse_quality_score = quality.score
        observe_ingest_quality_score(input_type="text", score=float(quality.score))
        observe_ingest_doc_type_quality_score(doc_type=document_type, score=float(quality.score))
        for structure_type, structure_score in quality.structure_scores.items():
            observe_ingest_structure_score(
                input_type="text",
                structure_type=structure_type,
                score=float(structure_score),
            )
            observe_ingest_doc_type_structure_score(
                doc_type=document_type,
                structure_type=structure_type,
                score=float(structure_score),
            )
        observe_ingest_stage(
            stage="parse",
            input_type="text",
            status="success",
            duration_ms=_elapsed_ms(parse_started),
        )
        observe_ingest_parse(input_type="text", status="ready", parser="raw_text")
        observe_ingest_doc_type(doc_type=document_type, status="ready")
        record_article_ready(article)
    elif draft.input_type == "url":
        article.preview_markdown = draft.preview_markdown or build_web_placeholder(
            title=draft.title,
            url=draft.source_url or "",
        )
        observe_ingest_doc_type(doc_type="webpage", status="queued")
        observe_ingest_stage(
            stage="parse",
            input_type="url",
            status="queued",
            duration_ms=0.0,
        )

    if article.clean_markdown:
        await index_article_content(session, article, user=user)

    job = None
    if article.parse_status != "ready":
        job = await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=draft.origin_search_session_id,
            dedupe_key=f"article_ingest:{article.id}",
            payload_json={"articleId": article.id, "inputType": article.input_type},
            created_at=now,
        )

    observe_ingest_stage(
        stage="end_to_end",
        input_type=draft.input_type,
        status="success" if article.parse_status == "ready" else "queued",
        duration_ms=_elapsed_ms(started_at),
    )
    return article, job
