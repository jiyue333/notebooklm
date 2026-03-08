from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.parser_router import parse_file_content
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.models import Article
from app.modules.search import repo_article
from app.modules.search.file_storage import build_storage_key, ensure_parent_dir
from app.modules.search.markdown_utils import (
    build_web_placeholder,
    compute_content_hash,
    extract_toc,
    normalize_text_to_markdown,
)


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
) -> Article | None:
    now = datetime.now(UTC)
    dedupe_key = _build_dedupe_key(draft)
    existing = await repo_article.list_existing_dedupe_keys(
        session,
        user_id=user_id,
        notebook_id=notebook_id,
        dedupe_keys=[dedupe_key],
    )
    if existing:
        return None

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
        absolute_path = ensure_parent_dir(storage_key)
        absolute_path.write_bytes(draft.file_bytes)
        article.file_storage_key = storage_key
        parsed = parse_file_content(
            file_name=draft.file_name,
            file_path=absolute_path,
            file_bytes=draft.file_bytes,
        )
        _apply_parsed_content(article, parsed.markdown, parsed.parser_name, now)
    elif draft.input_type == "text":
        markdown = normalize_text_to_markdown(title=draft.title, content=draft.raw_text_input or "")
        _apply_parsed_content(article, markdown, "raw_text", now)
    elif draft.input_type == "url":
        article.preview_markdown = draft.preview_markdown or build_web_placeholder(
            title=draft.title,
            url=draft.source_url or "",
        )

    if article.parse_status != "ready":
        await jobs_repo.create_article_ingest_job(
            session,
            article_id=article.id,
            search_session_id=draft.origin_search_session_id,
            dedupe_key=f"article_ingest:{article.id}",
            payload_json={"articleId": article.id, "inputType": article.input_type},
            created_at=now,
        )

    return article


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
    article.parser_name = parser_name
    article.parse_status = "ready"
    article.ingested_at = ingested_at


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
