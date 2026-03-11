from __future__ import annotations

from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.api.sse import encode_sse_event, extract_stream_text
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai.chat_context_builder import prepare_chat_reply
from app.modules.ai.chat_result_serializer import (
    build_chat_response,
    build_retrieval_snapshot,
)
from app.modules.ai.chat_runner import run_chat_completion
from app.modules.ai.conversation_rollup import maybe_rollup_conversation
from app.modules.ai.conversation_service import append_assistant_message

logger = structlog.get_logger(__name__)


async def reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
) -> dict:
    prepared = await prepare_chat_reply(
        session,
        user=user,
        notebook_id=notebook_id,
        conversation_id=conversation_id,
        article_id=article_id,
        message=message,
    )
    answer = await run_chat_completion(prepared)
    return await _finalize_chat_reply(session, prepared=prepared, answer=answer)


async def stream_reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
):
    prepared = await prepare_chat_reply(
        session,
        user=user,
        notebook_id=notebook_id,
        conversation_id=conversation_id,
        article_id=article_id,
        message=message,
    )

    async def event_stream():
        started_at = perf_counter()
        answer_parts: list[str] = []
        try:
            yield encode_sse_event(
                "start",
                {
                    "conversationId": prepared.conversation.id,
                    "route": prepared.route,
                },
            )
            async for chunk in prepared.model.astream(
                prepared.messages,
                config={"run_name": "chat_model", "metadata": prepared.trace_metadata},
            ):
                text = extract_stream_text(chunk)
                if not text:
                    continue
                answer_parts.append(text)
                yield encode_sse_event("token", {"content": text})

            answer = "".join(answer_parts).strip()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="success",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            if not answer:
                raise AppError(502, "对话生成失败", code="chat_generation_failed")

            result = await _finalize_chat_reply(session, prepared=prepared, answer=answer)
            yield encode_sse_event("done", result)
        except AppError as exc:
            await session.rollback()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="error",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            yield encode_sse_event(
                "error",
                {
                    "message": exc.message,
                    "code": exc.code,
                    "status": exc.status_code,
                    "meta": exc.meta,
                },
            )
        except Exception as exc:
            await session.rollback()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="error",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            logger.exception(
                "chat.stream_failed",
                conversation_id=prepared.conversation.id,
                error=str(exc),
            )
            yield encode_sse_event(
                "error",
                {
                    "message": "对话生成失败，请稍后重试",
                    "code": "chat_generation_failed",
                    "status": 502,
                    "meta": {},
                },
            )

    return event_stream()


async def _finalize_chat_reply(
    session: AsyncSession,
    *,
    prepared,
    answer: str,
) -> dict:
    retrieval_snapshot = build_retrieval_snapshot(
        route=prepared.route,
        route_reason=prepared.route_reason,
        route_confidence=prepared.route_confidence,
        query=prepared.user_message.content,
        retrieval_details=prepared.retrieval_details,
    )
    assistant_message = await append_assistant_message(
        session,
        conversation=prepared.conversation,
        article_id=prepared.user_message.article_id,
        route=prepared.route,
        content=answer,
        retrieval_snapshot=retrieval_snapshot,
    )
    try:
        await maybe_rollup_conversation(session, conversation=prepared.conversation, user=prepared.user)
    except Exception as exc:
        logger.exception(
            "chat.rollup_failed",
            conversation_id=prepared.conversation.id,
            error=str(exc),
        )
    await session.commit()
    return build_chat_response(
        conversation_id=prepared.conversation.id,
        message_id=assistant_message.id,
        route=prepared.route,
        reply=answer,
        citations=prepared.citations,
        retrieval_snapshot=retrieval_snapshot,
    )
