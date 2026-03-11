from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.modules.ai import summary_service


class DummySession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _decode_sse_event(raw_event: str) -> tuple[str, dict]:
    event = None
    payload = None
    for line in raw_event.strip().splitlines():
        if line.startswith("event: "):
            event = line.removeprefix("event: ").strip()
        if line.startswith("data: "):
            payload = json.loads(line.removeprefix("data: ").strip())
    return event or "", payload or {}


async def _collect_events(stream) -> list[tuple[str, dict]]:
    events = []
    async for raw_event in stream:
        events.append(_decode_sse_event(raw_event))
    return events


def _make_article():
    return SimpleNamespace(
        id="article-1",
        title="Example Article",
        clean_markdown="# Example Article\n\nBody text",
        content_hash="hash-1",
    )


def _make_settings():
    return {
        "modelProvider": "ollama",
        "modelName": "qwen3.5:0.8b",
        "outputLanguage": "中文",
    }


@pytest.mark.asyncio
async def test_stream_summary_returns_cached_summary(monkeypatch) -> None:
    session = DummySession()
    article = _make_article()

    async def fake_get_article(*args, **kwargs):
        return article

    async def fake_get_cache(*args, **kwargs):
        return SimpleNamespace(summary_text="cached summary")

    monkeypatch.setattr(summary_service.repo_article, "get_article", fake_get_article)
    monkeypatch.setattr(summary_service, "get_user_generation_settings", lambda user: _make_settings())
    monkeypatch.setattr(summary_service, "bind_observability_context", lambda **kwargs: None)
    monkeypatch.setattr(summary_service.ai_repo, "get_summary_cache", fake_get_cache)

    stream = await summary_service.stream_summary(
        session,
        user=SimpleNamespace(id="user-1"),
        notebook_id="notebook-1",
        article_id="article-1",
    )
    events = await _collect_events(stream)

    assert events == [
        ("start", {"cacheHit": True}),
        (
            "done",
            {
                "summary": "cached summary",
                "cacheHit": True,
                "promptVersion": summary_service.SUMMARY_PROMPT_VERSION,
            },
        ),
    ]
    assert session.commits == 0
    assert session.rollbacks == 0


@pytest.mark.asyncio
async def test_stream_summary_streams_tokens_and_caches_result(monkeypatch) -> None:
    session = DummySession()
    article = _make_article()
    created = []
    observed = []

    async def fake_get_article(*args, **kwargs):
        return article

    async def fake_get_cache(*args, **kwargs):
        return None

    async def fake_create_cache(_session, cache):
        created.append(cache)
        return cache

    class DummyPrompt:
        async def ainvoke(self, *_args, **_kwargs):
            return ["prompt-message"]

    class DummyModel:
        async def astream(self, *_args, **_kwargs):
            yield SimpleNamespace(content="第一段")
            yield SimpleNamespace(content="第二段")

    monkeypatch.setattr(summary_service.repo_article, "get_article", fake_get_article)
    monkeypatch.setattr(summary_service, "get_user_generation_settings", lambda user: _make_settings())
    monkeypatch.setattr(summary_service, "bind_observability_context", lambda **kwargs: None)
    monkeypatch.setattr(summary_service.ai_repo, "get_summary_cache", fake_get_cache)
    monkeypatch.setattr(summary_service.ai_repo, "create_summary_cache", fake_create_cache)
    monkeypatch.setattr(summary_service, "build_summary_prompt", lambda: DummyPrompt())
    monkeypatch.setattr(summary_service, "require_user_chat_model", lambda user: DummyModel())
    monkeypatch.setattr(summary_service, "observe_llm_call", lambda **kwargs: observed.append(kwargs))

    stream = await summary_service.stream_summary(
        session,
        user=SimpleNamespace(id="user-1"),
        notebook_id="notebook-1",
        article_id="article-1",
    )
    events = await _collect_events(stream)

    assert events[0] == ("start", {"cacheHit": False})
    assert events[1] == ("token", {"content": "第一段"})
    assert events[2] == ("token", {"content": "第二段"})
    assert events[3] == (
        "done",
        {
            "summary": "第一段第二段",
            "cacheHit": False,
            "promptVersion": summary_service.SUMMARY_PROMPT_VERSION,
        },
    )
    assert session.commits == 1
    assert session.rollbacks == 0
    assert created[0].summary_text == "第一段第二段"
    assert observed[0]["status"] == "success"
