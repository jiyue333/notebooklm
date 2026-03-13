"""chat 子包工具函数。

合并自原 rollup.py 和 message_mapper.py。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.chat_models import get_user_generation_settings, require_user_chat_model
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.modules.ai.chat import repo as chat_repo
from app.modules.ai.chat.context_builder import _build_trace_metadata
from app.modules.ai.chat.models import ConversationMessage
from app.modules.ai.prompts.chat_prompt import build_chat_rollup_prompt
from app.modules.tracker import LlmTracker

if TYPE_CHECKING:
    from app.modules.ai.chat.models import Conversation
    from app.modules.auth.models import User


# ---------------------------------------------------------------------------
# Message mapping (原 message_mapper.py)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Conversation rollup (原 rollup.py)
# ---------------------------------------------------------------------------

ROLLUP_TRIGGER_COUNT = 12
ROLLUP_KEEP_MESSAGES = 8


async def maybe_rollup_conversation(
    session: AsyncSession,
    *,
    conversation: Conversation,
    user: User,
) -> None:
    messages = await chat_repo.list_conversation_messages(
        session, conversation_id=conversation.id,
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
    trace_metadata = _build_trace_metadata(
        user=user,
        notebook_id=conversation.notebook_id,
        conversation_id=conversation.id,
        model_settings=model_settings,
    )
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
    tracker = LlmTracker.from_model_settings("chat_rollup", model_settings)
    tracker.mark_llm_start()
    try:
        result = await model.ainvoke(
            messages,
            config={"run_name": "chat_rollup_model", "metadata": trace_metadata},
        )
    except Exception:
        tracker.report_llm("error")
        raise
    summary, usage = extract_llm_text_and_usage(result)
    tracker.report_llm("success", usage=usage)
    if summary:
        conversation.rolling_summary = summary

    await chat_repo.delete_conversation_messages(
        session,
        message_ids=[message.id for message in overflow_messages],
    )
