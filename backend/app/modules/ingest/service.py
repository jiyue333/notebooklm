from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.repo import get_user_by_id
from app.infra.telemetry.metrics import observe_ingest_chunks, observe_ingest_parse, observe_ingest_ready
from app.modules.ingest.chunker import chunk_markdown
from app.modules.ingest.embedder import Embedder
from app.modules.ingest.indexer import replace_article_chunks
from app.modules.ingest.parser_router import parse_file_content
from app.modules.ingest.retrieval_text_builder import build_article_retrieval_text
from app.modules.jobs import repo as jobs_repo
from app.modules.jobs.models import Job
from app.modules.notebooks.models import Article
from app.modules.search import repo_article
from app.modules.search.file_storage import (
    build_storage_key,
    materialize_uploaded_file_for_parser,
    store_file_bytes,
)
from app.modules.search.markdown_utils import (
    build_web_placeholder,
    compute_content_hash,
    extract_toc,
    normalize_text_to_markdown,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class IngestDraft:
    input_type: str
    title: str
    preview_markdown: str | None = None
    source_url: str | None = None
    normalized_url: str | None = None
    raw_text_input: str | None = None
    file_name: str | None = None
    file_mime: str | None = None
    file_bytes: bytes | None = None
    origin_search_session_id: str | None = None
    origin_search_result_id: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    source_title_raw: str | None = None


async def ingest_draft(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    draft: IngestDraft,
) -> tuple[Article | None, Job | None]:
    now = datetime.now(UTC)
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise RuntimeError("user not found")
    dedupe_key = _build_dedupe_key(draft)
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
        file_ext=_extract_ext(draft.file_name),
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
        with materialize_uploaded_file_for_parser(
            file_name=draft.file_name,
            file_bytes=draft.file_bytes,
        ) as temp_path:
            parsed = parse_file_content(
                file_name=draft.file_name,
                file_path=temp_path,
                file_bytes=draft.file_bytes,
            )
        _apply_parsed_content(article, parsed.markdown, parsed.parser_name, now)
        if parsed.markdown:
            observe_ingest_parse(
                input_type="file",
                status="ready",
                parser=parsed.parser_name or "unknown",
            )
            record_article_ready(article)
    elif draft.input_type == "text":
        markdown = normalize_text_to_markdown(title=draft.title, content=draft.raw_text_input or "")
        _apply_parsed_content(article, markdown, "raw_text", now)
        observe_ingest_parse(input_type="text", status="ready", parser="raw_text")
        record_article_ready(article)
    elif draft.input_type == "url":
        article.preview_markdown = draft.preview_markdown or build_web_placeholder(
            title=draft.title,
            url=draft.source_url or "",
        )

    if article.clean_markdown:
        await _index_article_content(session, article, user=user)

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

    return article, job


def _apply_parsed_content(
    article: Article,
    markdown: str | None,
    parser_name: str | None,
    ingested_at: datetime,
) -> None:
    if not markdown:
        return
    article.clean_markdown = markdown
    article.preview_markdown = article.preview_markdown or markdown
    article.toc_json = extract_toc(markdown)
    article.content_hash = compute_content_hash(markdown)
    article.article_retrieval_text = build_article_retrieval_text(
        title=article.title,
        markdown=markdown,
        toc=article.toc_json,
    )
    article.parser_name = parser_name
    article.parse_status = "ready"
    article.ingested_at = ingested_at


def record_article_ready(article: Article) -> None:
    if article.parse_status != "ready" or not (article.clean_markdown or "").strip():
        return
    if article.created_at is None:
        return

    ready_at = article.ingested_at or datetime.now(UTC)
    duration_ms = max(
        (ready_at.astimezone(UTC) - article.created_at.astimezone(UTC)).total_seconds() * 1000,
        0.0,
    )
    observe_ingest_ready(input_type=article.input_type, duration_ms=duration_ms)
    logger.info(
        "ingest.article_ready",
        article_id=article.id,
        notebook_id=article.notebook_id,
        input_type=article.input_type,
        duration_ms=round(duration_ms, 2),
    )


async def _index_article_content(session: AsyncSession, article: Article, *, user) -> dict[str, float | int | str]:
    if not article.clean_markdown:
        return {
            "chunk_count": 0,
            "chunking_ms": 0.0,
            "embedding_ms": 0.0,
            "persist_ms": 0.0,
            "index_total_ms": 0.0,
            "embedding_status": "skipped_no_content",
        }

    total_started = perf_counter()
    chunk_started = perf_counter()
    chunks = chunk_markdown(article.clean_markdown, toc=article.toc_json)
    chunking_ms = round((perf_counter() - chunk_started) * 1000, 2)
    article.chunk_status = "ready" if chunks else "not_started"
    article.index_status = "ready"
    article.embedding_provider = None
    article.embedding_model = None
    article.embedding_profile_key = None
    article.embedding_dimension = None

    embedder = Embedder.from_user(user)
    article_vector = None
    chunk_vectors = None
    embedding_ms = 0.0
    embedding_status = "skipped_unconfigured"
    if embedder.is_configured:
        embedding_started = perf_counter()
        try:
            texts = [article.article_retrieval_text or article.title, *[chunk.chunk_text for chunk in chunks]]
            embeddings = await embedder.embed_texts(texts)
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
            if embeddings:
                article_vector = embeddings[0]
                chunk_vectors = embeddings[1:]
                article.embedding_provider = embedder.provider
                article.embedding_model = embedder.model_name
                article.embedding_profile_key = embedder.profile_key
                article.embedding_dimension = len(article_vector)
                embedding_status = "generated"
            else:
                embedding_status = "empty"
        except Exception as exc:
            embedding_ms = round((perf_counter() - embedding_started) * 1000, 2)
            embedding_status = "failed"
            logger.exception(
                "ingest.embedding_failed",
                article_id=article.id,
                error=str(exc),
                embedding_ms=embedding_ms,
            )

    article.article_vector = article_vector
    observe_ingest_chunks(input_type=article.input_type, chunk_count=len(chunks))
    persist_started = perf_counter()
    await replace_article_chunks(
        session,
        article=article,
        chunks=chunks,
        vectors=chunk_vectors,
    )
    persist_ms = round((perf_counter() - persist_started) * 1000, 2)
    total_ms = round((perf_counter() - total_started) * 1000, 2)
    stats = {
        "chunk_count": len(chunks),
        "chunking_ms": chunking_ms,
        "embedding_ms": embedding_ms,
        "persist_ms": persist_ms,
        "index_total_ms": total_ms,
        "embedding_status": embedding_status,
    }
    logger.info(
        "ingest.index_completed",
        article_id=article.id,
        notebook_id=article.notebook_id,
        input_type=article.input_type,
        provider=article.embedding_provider or embedder.provider,
        model=article.embedding_model or embedder.model_name,
        **stats,
    )
    return stats


def _build_dedupe_key(draft: IngestDraft) -> str:
    if draft.file_bytes is not None:
        return sha256(draft.file_bytes).hexdigest()
    if draft.normalized_url or draft.source_url:
        return sha256((draft.normalized_url or draft.source_url or "").encode("utf-8")).hexdigest()
    if draft.raw_text_input:
        return sha256(draft.raw_text_input.encode("utf-8")).hexdigest()
    return sha256((draft.preview_markdown or draft.title).encode("utf-8")).hexdigest()


def _extract_ext(file_name: str | None) -> str | None:
    if not file_name:
        return None
    suffix = file_name.rsplit(".", 1)
    if len(suffix) == 1:
        return None
    return suffix[-1].lower()
