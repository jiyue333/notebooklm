"""Chat service – the single entry point for chat interactions.

Manages conversation state and delegates to the ADR-004 pipeline.
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.chat import repo
from app.modules.ai.chat.pipeline import run_pipeline
from app.modules.ai.chat.pipeline.observer import ChatPipelineObserver
from app.modules.ai.chat.pipeline.types import ChatContext, ChatInput, ChatResult, ReadingCursor

logger = structlog.get_logger(__name__)


async def send_message(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    question: str,
    article_id: str | None = None,
    conversation_id: str | None = None,
    reading_cursor: dict | None = None,
    recent_highlights: list[str] | None = None,
    recent_turns: list[dict[str, str]] | None = None,
    user=None,
) -> ChatResult:
    """Process a chat message and return a structured result.

    This is the **only** public function external modules need to call.
    """

    # Load or create conversation
    conversation = None
    if conversation_id:
        conversation = await repo.get_conversation(
            db, conversation_id=conversation_id, user_id=user_id,
        )
    if conversation is None:
        conversation = await repo.create_conversation(
            db,
            user_id=user_id,
            notebook_id=notebook_id,
            article_id=article_id,
            title=question[:80],
        )
        await db.flush()

    # Persist user message
    await repo.append_message(
        db,
        conversation_id=conversation.id,
        role="user",
        content=question,
        article_id=article_id,
    )

    if recent_turns:
        turns = recent_turns[-6:]
    else:
        turns = [
            {"role": msg.role, "content": msg.content}
            for msg in await repo.list_recent_messages(db, conversation_id=conversation.id, limit=6)
        ]

    # Run pipeline
    observer = ChatPipelineObserver()
    chat_input = ChatInput(
        question=question,
        user_id=user_id,
        notebook_id=notebook_id,
        article_id=article_id,
        conversation_id=conversation.id,
        reading_cursor=ReadingCursor(
            page=reading_cursor.get("page"),
            section_id=reading_cursor.get("sectionId") or reading_cursor.get("section_id"),
            block_id=reading_cursor.get("blockId") or reading_cursor.get("block_id"),
        ) if reading_cursor else None,
        recent_highlights=recent_highlights or [],
        recent_turns=turns,
    )
    ctx = ChatContext(chat_input=chat_input, user=user)
    result = await run_pipeline(ctx, db, observer=observer)

    # Persist assistant message (dict for JSONB column)
    retrieval_snapshot = json.loads(json.dumps({
        "evidence_spans": result.evidence_spans,
        "related_articles": result.related_articles,
    }, ensure_ascii=False, default=str))

    assistant_message = await repo.append_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer_text,
        article_id=article_id,
        route=result.route.value,
        retrieval_snapshot_json=retrieval_snapshot,
    )

    result.conversation_id = conversation.id
    result.message_id = assistant_message.id
    await db.commit()
    return result
