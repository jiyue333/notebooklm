from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, HumanMessage

from app.api.errors import AppError
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai import repo as ai_repo
from app.modules.ai.langchain_factory import (
    build_chat_rollup_prompt,
    get_user_generation_settings,
    require_user_chat_model,
)
from app.modules.ai.models import Conversation, ConversationMessage

RECENT_WINDOW_SIZE = 10
ROLLUP_TRIGGER_COUNT = 12
ROLLUP_KEEP_MESSAGES = 8


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
    history = [message for message in messages if message.id != exclude_message_id]
    return [to_langchain_message(message) for message in history]


def to_langchain_message(message: ConversationMessage):
    if message.role == "assistant":
        return AIMessage(content=message.content)
    return HumanMessage(content=message.content)


async def maybe_rollup_conversation(session, *, conversation: Conversation, user) -> None:
    messages = await ai_repo.list_conversation_messages(
        session,
        conversation_id=conversation.id,
    )
    if len(messages) <= ROLLUP_TRIGGER_COUNT:
        return

    overflow_messages = messages[:-ROLLUP_KEEP_MESSAGES]
    transcript = "\n".join(
        f"{'用户' if message.role == 'user' else '助手'}：{message.content}"
        for message in overflow_messages
    ).strip()
    if not transcript:
        return

    model_settings = get_user_generation_settings(user)
    trace_metadata = {
        "user_id": user.id,
        "conversation_id": conversation.id,
        "notebook_id": conversation.notebook_id,
        "provider": model_settings["modelProvider"],
        "model_name": model_settings["modelName"],
    }
    prompt = build_chat_rollup_prompt()
    model = require_user_chat_model(user)
    messages = await prompt.ainvoke(
        {
            "output_language": model_settings["outputLanguage"],
            "existing_summary": conversation.rolling_summary or "暂无历史摘要。",
            "conversation": transcript,
        },
        config={"run_name": "chat_rollup_prompt", "metadata": trace_metadata},
    )
    started_at = perf_counter()
    try:
        result = await model.ainvoke(
            messages,
            config={"run_name": "chat_rollup_model", "metadata": trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="chat_rollup",
            provider=model_settings["modelProvider"],
            model=model_settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    summary, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="chat_rollup",
        provider=model_settings["modelProvider"],
        model=model_settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    if summary:
        conversation.rolling_summary = summary

    await ai_repo.delete_conversation_messages(
        session,
        message_ids=[message.id for message in overflow_messages],
    )
