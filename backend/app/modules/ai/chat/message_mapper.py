from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.modules.ai.chat.models import ConversationMessage


def to_langchain_message(message: ConversationMessage):
    if message.role == "assistant":
        return AIMessage(content=message.content)
    return HumanMessage(content=message.content)


def to_langchain_history(
    messages: list[ConversationMessage],
    *,
    exclude_message_id: str | None = None,
) -> list:
    history = [message for message in messages if message.id != exclude_message_id]
    return [to_langchain_message(message) for message in history]
