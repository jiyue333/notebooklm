from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.modules.ingest import service as ingest_service
from app.modules.notebooks.assembler import build_article_view
from app.modules.retrieval.router import _fallback_route, route_chat_message


def make_article(**overrides):
    defaults = {
        "id": "article-1",
        "notebook_id": "notebook-1",
        "title": "Example Article",
        "author": "tester",
        "published_at": None,
        "created_at": datetime(2026, 3, 10, tzinfo=UTC),
        "file_mime": None,
        "file_name": None,
        "file_storage_key": None,
        "clean_markdown": "# Example Article\n\nBody text",
        "toc_json": [{"id": "body-text", "title": "Body text", "level": 2}],
        "parse_status": "ready",
        "chunk_status": "processing",
        "index_status": "processing",
        "parse_error_message": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_build_article_view_shows_content_before_index_finishes() -> None:
    article = make_article()

    view = build_article_view(article)

    assert view["contentReady"] is True
    assert view["content"] == article.clean_markdown
    assert view["chunkStatus"] == "processing"
    assert view["indexStatus"] == "processing"
    assert view["processingHint"] == ""


@pytest.mark.asyncio
async def test_route_chat_message_detects_general_question_even_with_current_article() -> None:
    decision = await route_chat_message(
        user=SimpleNamespace(),
        notebook_title="Notebook",
        article_id="article-1",
        message="你能做什么？",
    )

    assert decision.route == "GENERAL"


def test_fallback_route_defaults_to_general_without_article() -> None:
    decision = _fallback_route(message="随便聊聊", article_id=None)

    assert decision.route == "GENERAL"


def test_record_article_ready_observes_duration_and_logs(monkeypatch) -> None:
    article = make_article(
        input_type="search_result",
        ingested_at=datetime(2026, 3, 10, 0, 0, 5, tzinfo=UTC),
    )
    observed = []
    logged = []

    monkeypatch.setattr(ingest_service, "observe_ingest_ready", lambda **kwargs: observed.append(kwargs))
    monkeypatch.setattr(ingest_service.logger, "info", lambda event, **kwargs: logged.append((event, kwargs)))

    ingest_service.record_article_ready(article)

    assert observed == [{"input_type": "search_result", "duration_ms": 5000.0}]
    assert logged == [
        (
            "ingest.article_ready",
            {
                "article_id": "article-1",
                "notebook_id": "notebook-1",
                "input_type": "search_result",
                "duration_ms": 5000.0,
            },
        )
    ]
