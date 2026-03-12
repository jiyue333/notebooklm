from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.chat.models import Conversation, ConversationMessage


async def get_conversation_by_id(
    session: AsyncSession,
    *,
    conversation_id: str,
) -> Conversation | None:
    result = await session.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    return result.scalar_one_or_none()


async def create_conversation(session: AsyncSession, conversation: Conversation) -> Conversation:
    session.add(conversation)
    await session.flush()
    return conversation


async def create_message(
    session: AsyncSession,
    message: ConversationMessage,
) -> ConversationMessage:
    session.add(message)
    await session.flush()
    return message


async def list_conversation_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
    limit: int | None = None,
) -> list[ConversationMessage]:
    if limit is not None:
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(desc(ConversationMessage.created_at))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(reversed(result.scalars().all()))

    result = await session.execute(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc())
    )
    return list(result.scalars().all())


async def delete_conversation_messages(
    session: AsyncSession,
    *,
    message_ids: Sequence[str],
) -> None:
    if not message_ids:
        return
    await session.execute(
        delete(ConversationMessage).where(ConversationMessage.id.in_(list(message_ids)))
    )

