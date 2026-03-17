"""聊天会话持久化仓储。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.chat.models import Conversation, ConversationMessage


async def get_conversation(
    session: AsyncSession,
    *,
    conversation_id: str,
    user_id: str,
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_conversation(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    article_id: str | None = None,
    title: str | None = None,
) -> Conversation:
    now = datetime.now(UTC)
    conv = Conversation(
        user_id=user_id,
        notebook_id=notebook_id,
        current_article_id=article_id,
        title=title,
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    session.add(conv)
    await session.flush()
    return conv


async def append_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    role: str,
    content: str,
    article_id: str | None = None,
    route: str | None = None,
    retrieval_snapshot_json: dict | None = None,
) -> ConversationMessage:
    msg = ConversationMessage(
        conversation_id=conversation_id,
        article_id=article_id,
        role=role,
        route=route,
        content=content,
        retrieval_snapshot_json=retrieval_snapshot_json,
        created_at=datetime.now(UTC),
    )
    session.add(msg)
    await session.flush()
    return msg


async def list_recent_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
    limit: int = 6,
) -> list[ConversationMessage]:
    result = await session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


