from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.infra.telemetry.metrics import observe_ingest_ready
from app.modules.ingest.indexing.retrieval_text_builder import build_article_retrieval_text
from app.modules.notebooks.models import Article
from app.modules.search.markdown_utils import compute_content_hash, extract_toc

logger = structlog.get_logger(__name__)


def apply_parsed_content(
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
