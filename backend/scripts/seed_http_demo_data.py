#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from sqlalchemy import delete, or_

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.infra.db.session import get_session_manager
from app.modules.ai.models import Conversation, ConversationMessage, SummaryCache
from app.modules.ai.prompts.summary_prompt import SUMMARY_PROMPT_VERSION
from app.modules.auth.models import AuthToken, User
from app.modules.auth.security import hash_password
from app.modules.ingest.chunker import chunk_markdown
from app.modules.ingest.indexer import replace_article_chunks
from app.modules.jobs.models import Job
from app.modules.notes.models import Note
from app.modules.notebooks.models import Article, Notebook
from app.modules.search.file_storage import build_storage_key, store_file_bytes
from app.modules.search.markdown_utils import compute_content_hash, extract_toc
from app.modules.search.models import SearchResult, SearchSession
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS

DEMO_USER_ID = "10000000-0000-0000-0000-000000000001"
NO_KEY_USER_ID = "10000000-0000-0000-0000-000000000002"

NOTEBOOK_EMPTY_ID = "20000000-0000-0000-0000-000000000001"
NOTEBOOK_MIXED_ID = "20000000-0000-0000-0000-000000000002"
NOTEBOOK_NO_KEY_ID = "20000000-0000-0000-0000-000000000003"

NOTE_SEED_ID = "30000000-0000-0000-0000-000000000001"
NOTE_GUIDE_ID = "30000000-0000-0000-0000-000000000002"

ARTICLE_READY_ID = "40000000-0000-0000-0000-000000000001"
ARTICLE_FILE_ID = "40000000-0000-0000-0000-000000000002"
ARTICLE_QUEUED_ID = "40000000-0000-0000-0000-000000000003"
ARTICLE_FAILED_ID = "40000000-0000-0000-0000-000000000004"

SEARCH_SESSION_COMPLETED_ID = "50000000-0000-0000-0000-000000000001"
SEARCH_SESSION_FAILED_ID = "50000000-0000-0000-0000-000000000002"
SEARCH_SESSION_EXPIRED_ID = "50000000-0000-0000-0000-000000000003"

SEARCH_RESULT_ALPHA_ID = "51000000-0000-0000-0000-000000000001"
SEARCH_RESULT_BETA_ID = "51000000-0000-0000-0000-000000000002"

JOB_PENDING_ID = "60000000-0000-0000-0000-000000000001"
JOB_FAILED_ID = "60000000-0000-0000-0000-000000000002"

CONVERSATION_SEED_ID = "70000000-0000-0000-0000-000000000001"
MESSAGE_USER_ID = "71000000-0000-0000-0000-000000000001"
MESSAGE_ASSISTANT_ID = "71000000-0000-0000-0000-000000000002"

SUMMARY_CACHE_ID = "72000000-0000-0000-0000-000000000001"


def _url_hash(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _build_demo_markdown() -> str:
    return """# Agent Memory for Research

## Why it matters

When a research workspace keeps structured notes, later summarization and chat become much more stable.

## Practical takeaways

- Keep article titles and notebook titles explicit.
- Separate source ingestion from note writing.
- Store enough clean markdown for retrieval.
"""


def _build_file_markdown() -> str:
    return """# HTTP Replay Collection Notes

## Goal

This markdown file is seeded so the file download API has a stable target.

## Included checks

- notebook detail can render markdown file articles
- file endpoint can return an uploaded file
- import and manual source APIs can coexist in one notebook
"""


def _build_ready_summary() -> str:
    return "这篇文章强调：研究工作区需要结构化来源、稳定的 clean markdown，以及与笔记解耦的摄取链路。"


async def _reset_demo_rows(session) -> None:
    demo_user_ids = [DEMO_USER_ID, NO_KEY_USER_ID]
    notebook_ids = [NOTEBOOK_EMPTY_ID, NOTEBOOK_MIXED_ID, NOTEBOOK_NO_KEY_ID]
    article_ids = [ARTICLE_READY_ID, ARTICLE_FILE_ID, ARTICLE_QUEUED_ID, ARTICLE_FAILED_ID]
    search_session_ids = [
        SEARCH_SESSION_COMPLETED_ID,
        SEARCH_SESSION_FAILED_ID,
        SEARCH_SESSION_EXPIRED_ID,
    ]

    await session.execute(delete(ConversationMessage).where(ConversationMessage.conversation_id == CONVERSATION_SEED_ID))
    await session.execute(delete(Conversation).where(Conversation.id == CONVERSATION_SEED_ID))
    await session.execute(delete(SummaryCache).where(SummaryCache.id == SUMMARY_CACHE_ID))
    await session.execute(delete(Job).where(or_(Job.id.in_([JOB_PENDING_ID, JOB_FAILED_ID]), Job.article_id.in_(article_ids), Job.search_session_id.in_(search_session_ids))))
    await session.execute(delete(AuthToken).where(AuthToken.user_id.in_(demo_user_ids)))
    await session.execute(delete(SearchResult).where(SearchResult.search_session_id.in_(search_session_ids)))
    await session.execute(delete(SearchSession).where(SearchSession.id.in_(search_session_ids)))
    await session.execute(delete(Note).where(Note.id.in_([NOTE_SEED_ID, NOTE_GUIDE_ID])))
    await session.execute(delete(Article).where(Article.id.in_(article_ids)))
    await session.execute(delete(Notebook).where(Notebook.id.in_(notebook_ids)))
    await session.execute(delete(User).where(User.id.in_(demo_user_ids)))
    await session.commit()


async def _seed_demo_rows(session) -> None:
    now = datetime.now(UTC)
    ready_markdown = _build_demo_markdown()
    file_markdown = _build_file_markdown()
    ready_hash = compute_content_hash(ready_markdown)
    file_hash = compute_content_hash(file_markdown)

    demo_user = User(
        id=DEMO_USER_ID,
        name="demo-http",
        email="demo-http@example.com",
        password_hash=hash_password("demo-secret"),
        settings_json=dict(DEFAULT_USER_SETTINGS),
        created_at=now - timedelta(days=10),
        updated_at=now - timedelta(hours=2),
    )
    no_key_user = User(
        id=NO_KEY_USER_ID,
        name="demo-nokey",
        email="demo-nokey@example.com",
        password_hash=hash_password("demo-nokey-secret"),
        settings_json={
            **DEFAULT_USER_SETTINGS,
            "modelProvider": "ollama",
            "modelName": " ",
            "apiUrl": " ",
            "embeddingProvider": "ollama",
            "embeddingModel": " ",
            "embeddingApiUrl": " ",
        },
        created_at=now - timedelta(days=9),
        updated_at=now - timedelta(hours=1),
    )
    session.add_all([demo_user, no_key_user])

    notebooks = [
        Notebook(
            id=NOTEBOOK_EMPTY_ID,
            user_id=DEMO_USER_ID,
            title="Empty Playground",
            emoji="🫙",
            color="sand",
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=1),
        ),
        Notebook(
            id=NOTEBOOK_MIXED_ID,
            user_id=DEMO_USER_ID,
            title="HTTP Demo Notebook",
            emoji="🧪",
            color="ocean",
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(minutes=20),
        ),
        Notebook(
            id=NOTEBOOK_NO_KEY_ID,
            user_id=NO_KEY_USER_ID,
            title="No Key Notebook",
            emoji="🔒",
            color="slate",
            created_at=now - timedelta(days=4),
            updated_at=now - timedelta(days=1),
        ),
    ]
    session.add_all(notebooks)

    notes = [
        Note(
            id=NOTE_SEED_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            title="Seeded note",
            content_markdown="## Seeded note\n\nThis note is pre-created for HTTP replay flows.\n",
            note_type="outline",
            source_count=2,
            created_at=now - timedelta(days=3),
            updated_at=now - timedelta(hours=12),
        ),
        Note(
            id=NOTE_GUIDE_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            title="Request checklist",
            content_markdown="- login\n- notebook detail\n- import source\n",
            note_type="checklist",
            source_count=1,
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=6),
        ),
    ]
    session.add_all(notes)

    file_storage_key = build_storage_key(
        notebook_id=NOTEBOOK_MIXED_ID,
        article_id=ARTICLE_FILE_ID,
        filename="demo-outline.md",
    )
    store_file_bytes(
        storage_key=file_storage_key,
        data=file_markdown.encode("utf-8"),
        content_type="text/markdown",
    )

    articles = [
        Article(
            id=ARTICLE_READY_ID,
            user_id=DEMO_USER_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            input_type="text",
            dedupe_key=_url_hash("article-ready-seed"),
            source_title_raw="Agent Memory for Research",
            raw_text_input=ready_markdown,
            title="Agent Memory for Research",
            author="NotebookLM Demo",
            language="zh",
            preview_markdown=ready_markdown,
            clean_markdown=ready_markdown,
            toc_json=extract_toc(ready_markdown),
            content_hash=ready_hash,
            parser_name="seed_script",
            parse_status="ready",
            parse_quality_score=0.96,
            article_retrieval_text="Agent Memory for Research structured clean markdown retrieval note writing",
            chunk_status="ready",
            index_status="ready",
            ingested_at=now - timedelta(days=2),
            created_at=now - timedelta(days=2),
            updated_at=now - timedelta(hours=8),
        ),
        Article(
            id=ARTICLE_FILE_ID,
            user_id=DEMO_USER_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            input_type="file",
            dedupe_key=_url_hash("article-file-seed"),
            source_title_raw="demo-outline.md",
            file_name="demo-outline.md",
            file_ext="md",
            file_mime="text/markdown",
            file_size=len(file_markdown.encode("utf-8")),
            file_storage_key=file_storage_key,
            title="HTTP Replay Collection Notes",
            author="NotebookLM Demo",
            language="zh",
            preview_markdown=file_markdown,
            clean_markdown=file_markdown,
            toc_json=extract_toc(file_markdown),
            content_hash=file_hash,
            parser_name="seed_script",
            parse_status="ready",
            parse_quality_score=0.94,
            article_retrieval_text="HTTP replay collection notes bruno real request run download file",
            chunk_status="ready",
            index_status="ready",
            ingested_at=now - timedelta(days=1),
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(hours=5),
        ),
        Article(
            id=ARTICLE_QUEUED_ID,
            user_id=DEMO_USER_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            input_type="url",
            source_url="https://example.com/waiting",
            normalized_url="https://example.com/waiting",
            dedupe_key=_url_hash("https://example.com/waiting"),
            source_title_raw="Queued source",
            title="Queued source",
            preview_markdown="# Queued source\n\n来源链接：https://example.com/waiting\n\n该来源已加入，等待正文抓取和解析。\n",
            parse_status="queued",
            article_retrieval_text="Queued source waiting parser",
            chunk_status="not_started",
            index_status="not_started",
            created_at=now - timedelta(hours=12),
            updated_at=now - timedelta(hours=2),
        ),
        Article(
            id=ARTICLE_FAILED_ID,
            user_id=DEMO_USER_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            input_type="url",
            source_url="https://example.com/broken",
            normalized_url="https://example.com/broken",
            dedupe_key=_url_hash("https://example.com/broken"),
            source_title_raw="Broken source",
            title="Broken source",
            preview_markdown="# Broken source\n\n来源链接：https://example.com/broken\n",
            parse_status="failed",
            parse_error_tag="provider_fetch_failed",
            parse_error_message="seeded failure for manual HTTP replay",
            article_retrieval_text="Broken source failed parser",
            chunk_status="not_started",
            index_status="not_started",
            created_at=now - timedelta(hours=10),
            updated_at=now - timedelta(hours=1),
        ),
    ]
    session.add_all(articles)
    await session.flush()

    for article in (articles[0], articles[1]):
        chunks = chunk_markdown(article.clean_markdown or "", toc=article.toc_json)
        await replace_article_chunks(session, article=article, chunks=chunks, vectors=None)

    summary_cache = SummaryCache(
        id=SUMMARY_CACHE_ID,
        user_id=DEMO_USER_ID,
        article_id=ARTICLE_READY_ID,
        content_hash=ready_hash,
        prompt_version=SUMMARY_PROMPT_VERSION,
        model_provider=DEFAULT_USER_SETTINGS["modelProvider"],
        model_name=DEFAULT_USER_SETTINGS["modelName"],
        output_language=DEFAULT_USER_SETTINGS["outputLanguage"],
        summary_text=_build_ready_summary(),
        created_at=now - timedelta(hours=3),
        updated_at=now - timedelta(hours=3),
    )
    session.add(summary_cache)

    completed_search = SearchSession(
        id=SEARCH_SESSION_COMPLETED_ID,
        user_id=DEMO_USER_ID,
        notebook_id=NOTEBOOK_MIXED_ID,
        query="memory architecture",
        normalized_query="memory architecture",
        mode="fast",
        execution_mode="sync",
        provider_name="exa",
        provider_request_json={"query": "memory architecture", "mode": "fast", "maxResults": 5},
        status="completed",
        mode_label="Fast Research",
        result_count=2,
        created_at=now - timedelta(hours=8),
        completed_at=now - timedelta(hours=8),
        expires_at=now + timedelta(days=1),
    )
    failed_search = SearchSession(
        id=SEARCH_SESSION_FAILED_ID,
        user_id=DEMO_USER_ID,
        notebook_id=NOTEBOOK_MIXED_ID,
        query="broken provider",
        normalized_query="broken provider",
        mode="deep",
        execution_mode="async",
        provider_name="exa",
        provider_request_json={"query": "broken provider", "mode": "deep", "maxResults": 10},
        status="failed",
        mode_label="Deep Research",
        result_count=0,
        error_code="provider_search_failed",
        error_message="seeded provider failure",
        created_at=now - timedelta(hours=7),
        completed_at=now - timedelta(hours=7),
        expires_at=now + timedelta(hours=12),
    )
    expired_search = SearchSession(
        id=SEARCH_SESSION_EXPIRED_ID,
        user_id=DEMO_USER_ID,
        notebook_id=NOTEBOOK_MIXED_ID,
        query="expired session",
        normalized_query="expired session",
        mode="auto",
        execution_mode="sync",
        provider_name="exa",
        provider_request_json={"query": "expired session", "mode": "auto", "maxResults": 3},
        status="completed",
        mode_label="Auto Research",
        result_count=0,
        created_at=now - timedelta(days=2),
        completed_at=now - timedelta(days=2),
        expires_at=now - timedelta(hours=1),
    )
    session.add_all([completed_search, failed_search, expired_search])

    session.add_all(
        [
            SearchResult(
                id=SEARCH_RESULT_ALPHA_ID,
                search_session_id=SEARCH_SESSION_COMPLETED_ID,
                provider_result_id="exa-alpha",
                raw_url="https://example.com/alpha",
                canonical_url="https://example.com/alpha",
                url_hash=_url_hash("https://example.com/alpha"),
                title="Alpha Memory Paper",
                description="How structured workspace memory improves later retrieval.",
                author="Alice",
                domain="example.com",
                favicon_url=None,
                display_rank=1,
                preview_markdown="## Highlights\n\n- Structured memory improves retrieval.\n- Notes should stay separate from ingestion.\n",
                raw_payload_json={},
                created_at=now - timedelta(hours=8),
            ),
            SearchResult(
                id=SEARCH_RESULT_BETA_ID,
                search_session_id=SEARCH_SESSION_COMPLETED_ID,
                provider_result_id="exa-beta",
                raw_url="https://example.com/beta",
                canonical_url="https://example.com/beta",
                url_hash=_url_hash("https://example.com/beta"),
                title="Beta Research Workflow",
                description="An operational checklist for article import and note creation.",
                author="Bob",
                domain="example.com",
                favicon_url=None,
                display_rank=2,
                preview_markdown="## Highlights\n\n- Import first.\n- Summarize after clean markdown is ready.\n",
                raw_payload_json={},
                created_at=now - timedelta(hours=8),
            ),
        ]
    )

    session.add_all(
        [
            Job(
                id=JOB_PENDING_ID,
                job_type="article_ingest",
                article_id=ARTICLE_QUEUED_ID,
                search_session_id=None,
                dedupe_key=f"article_ingest:{ARTICLE_QUEUED_ID}",
                payload_json={"articleId": ARTICLE_QUEUED_ID, "inputType": "url"},
                status="pending_publish",
                attempts=0,
                max_attempts=3,
                created_at=now - timedelta(hours=2),
                available_at=now - timedelta(hours=2),
            ),
            Job(
                id=JOB_FAILED_ID,
                job_type="search_deep",
                article_id=None,
                search_session_id=SEARCH_SESSION_FAILED_ID,
                dedupe_key=f"search_deep:{SEARCH_SESSION_FAILED_ID}",
                payload_json={"searchSessionId": SEARCH_SESSION_FAILED_ID},
                status="failed",
                attempts=2,
                max_attempts=3,
                last_error="seeded job failure",
                created_at=now - timedelta(hours=6),
                available_at=now - timedelta(hours=6),
                finished_at=now - timedelta(hours=6),
            ),
        ]
    )

    session.add(
        Conversation(
            id=CONVERSATION_SEED_ID,
            user_id=DEMO_USER_ID,
            notebook_id=NOTEBOOK_MIXED_ID,
            current_article_id=ARTICLE_READY_ID,
            title="Seeded research thread",
            rolling_summary="用户在讨论 research memory 与 ingestion pipeline。",
            last_message_at=now - timedelta(minutes=30),
            created_at=now - timedelta(hours=4),
            updated_at=now - timedelta(minutes=30),
        )
    )
    session.add_all(
        [
            ConversationMessage(
                id=MESSAGE_USER_ID,
                conversation_id=CONVERSATION_SEED_ID,
                article_id=ARTICLE_READY_ID,
                role="user",
                content="这篇文章主要讲了什么？",
                created_at=now - timedelta(hours=1),
            ),
            ConversationMessage(
                id=MESSAGE_ASSISTANT_ID,
                conversation_id=CONVERSATION_SEED_ID,
                article_id=ARTICLE_READY_ID,
                role="assistant",
                route="CURRENT_ARTICLE",
                content="它强调研究工作区需要结构化 clean markdown 和稳定的来源管理。",
                retrieval_snapshot_json={
                    "route": "CURRENT_ARTICLE",
                    "articles": [{"articleId": ARTICLE_READY_ID, "title": "Agent Memory for Research"}],
                },
                created_at=now - timedelta(minutes=50),
            ),
        ]
    )

    await session.commit()


async def seed_dataset() -> dict:
    async for session in get_session_manager().session():
        await _reset_demo_rows(session)
        await _seed_demo_rows(session)
        return {
            "users": {
                "demo": {
                    "id": DEMO_USER_ID,
                    "username": "demo-http",
                    "password": "demo-secret",
                },
                "noKey": {
                    "id": NO_KEY_USER_ID,
                    "username": "demo-nokey",
                    "password": "demo-nokey-secret",
                },
            },
            "notebooks": {
                "empty": NOTEBOOK_EMPTY_ID,
                "mixed": NOTEBOOK_MIXED_ID,
                "noKey": NOTEBOOK_NO_KEY_ID,
            },
            "notes": {
                "seed": NOTE_SEED_ID,
                "guide": NOTE_GUIDE_ID,
            },
            "articles": {
                "ready": ARTICLE_READY_ID,
                "file": ARTICLE_FILE_ID,
                "queued": ARTICLE_QUEUED_ID,
                "failed": ARTICLE_FAILED_ID,
            },
            "searchSessions": {
                "completed": SEARCH_SESSION_COMPLETED_ID,
                "failed": SEARCH_SESSION_FAILED_ID,
                "expired": SEARCH_SESSION_EXPIRED_ID,
            },
            "searchResults": {
                "alpha": SEARCH_RESULT_ALPHA_ID,
                "beta": SEARCH_RESULT_BETA_ID,
            },
            "conversationId": CONVERSATION_SEED_ID,
        }
    raise RuntimeError("database session unavailable")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed stable HTTP demo data into the configured database.")
    parser.parse_args()
    manifest = asyncio.run(seed_dataset())
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
