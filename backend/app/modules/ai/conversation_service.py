from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.api.errors import AppError
from app.modules.ai import repo as ai_repo
from app.modules.ai.message_mapper import to_langchain_history
from app.modules.ai.models import Conversation, ConversationMessage

RECENT_WINDOW_SIZE = 10


async def load_or_create_conversation(
    session,
    *,
    user_id: str,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
) -> Conversation:
    conversation = None
    if conversation_id:
        try:
            UUID(conversation_id)
        except ValueError:
            conversation_id = None
        existing = (
            await ai_repo.get_conversation_by_id(session, conversation_id=conversation_id)
            if conversation_id
            else None
        )
        if existing is not None:
            if existing.user_id != user_id or existing.notebook_id != notebook_id:
                raise AppError(404, "未找到对应会话", code="conversation_not_found")
            conversation = existing

    if conversation is None:
        conversation = await ai_repo.create_conversation(
            session,
            Conversation(
                id=conversation_id or str(uuid4()),
                user_id=user_id,
                notebook_id=notebook_id,
                current_article_id=article_id,
                last_message_at=datetime.now(UTC),
            ),
        )
    elif article_id:
        conversation.current_article_id = article_id
        conversation.last_message_at = datetime.now(UTC)

    return conversation


async def append_user_message(
    session,
    *,
    conversation: Conversation,
    article_id: str | None,
    content: str,
) -> ConversationMessage:
    conversation.last_message_at = datetime.now(UTC)
    return await ai_repo.create_message(
        session,
        ConversationMessage(
            conversation_id=conversation.id,
            article_id=article_id,
            role="user",
            content=content,
        ),
    )


async def append_assistant_message(
    session,
    *,
    conversation: Conversation,
    article_id: str | None,
    route: str,
    content: str,
    retrieval_snapshot: dict | None,
) -> ConversationMessage:
    conversation.last_message_at = datetime.now(UTC)
    return await ai_repo.create_message(
        session,
        ConversationMessage(
            conversation_id=conversation.id,
            article_id=article_id,
            role="assistant",
            route=route,
            content=content,
            retrieval_snapshot_json=retrieval_snapshot,
        ),
    )


async def load_history_messages(
    session,
    *,
    conversation_id: str,
    exclude_message_id: str | None = None,
) -> list:
    messages = await ai_repo.list_conversation_messages(
        session,
        conversation_id=conversation_id,
        limit=RECENT_WINDOW_SIZE + (1 if exclude_message_id else 0),
    )
    return to_langchain_history(messages, exclude_message_id=exclude_message_id)
