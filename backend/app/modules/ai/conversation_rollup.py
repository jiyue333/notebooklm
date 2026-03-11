from __future__ import annotations

from time import perf_counter

from app.infra.ai.chat_models import get_user_generation_settings, require_user_chat_model
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai import repo as ai_repo
from app.modules.ai.langchain_factory import build_chat_rollup_prompt

ROLLUP_TRIGGER_COUNT = 12
ROLLUP_KEEP_MESSAGES = 8


async def maybe_rollup_conversation(session, *, conversation, user) -> None:
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
