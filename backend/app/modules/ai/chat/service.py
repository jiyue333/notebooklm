from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.api.sse import build_sse_error_payload, encode_sse_event, extract_stream_text
from app.infra.telemetry.tracing import finish_span, start_span, start_span_now, traced
from app.modules.ai.chat.context_builder import PreparedChatReply, prepare_chat_reply
from app.modules.ai.chat.conversation import append_assistant_message
from app.modules.ai.chat.result_serializer import (
    build_chat_response,
    build_retrieval_snapshot,
)
from app.modules.ai.chat.utils import maybe_rollup_conversation
from app.modules.tracker import AiReviewTracker, LlmTracker

if TYPE_CHECKING:
    from app.modules.auth.models import User

logger = structlog.get_logger(__name__)


async def stream_reply(
    session: AsyncSession,
    *,
    user: User,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
):
    tracker = LlmTracker(operation="chat")
    try:
        prepared = await prepare_chat_reply(
            session,
            user=user,
            notebook_id=notebook_id,
            conversation_id=conversation_id,
            article_id=article_id,
            message=message,
        )
    except Exception:
        tracker.report_request("stream", "error")
        raise

    tracker = LlmTracker.from_model_settings("chat", prepared.model_settings)

    async def event_stream():
        tracker.mark_llm_start()
        first_token_span = start_span_now(
            "chat.model_first_token",
            attributes={
                "provider": tracker.provider,
                "model_name": tracker.model,
                "route": prepared.route,
            },
        )
        first_token_recorded = False
        answer_parts: list[str] = []
        try:
            yield encode_sse_event(
                "start",
                {
                    "conversationId": prepared.conversation.id,
                    "route": prepared.route,
                },
            )
            with start_span(
                "chat.model_stream",
                attributes={
                    "provider": tracker.provider,
                    "model_name": tracker.model,
                    "route": prepared.route,
                },
            ):
                async for chunk in prepared.model.astream(
                    prepared.messages,
                    config={"run_name": "chat_model", "metadata": prepared.trace_metadata},
                ):
                    text = extract_stream_text(chunk)
                    if not text:
                        continue
                    if not first_token_recorded:
                        ttft_ms = tracker.llm_ms
                        tracker.report_first_token(ttft_ms)
                        finish_span(first_token_span, attributes={"duration_ms": ttft_ms})
                        first_token_span = None
                        first_token_recorded = True
                    answer_parts.append(text)
                    yield encode_sse_event("token", {"content": text})

            answer = "".join(answer_parts).strip()
            if not answer:
                raise AppError(502, "对话生成失败", code="chat_generation_failed")

            result = await _finalize_chat_reply(session, prepared=prepared, answer=answer)
            _schedule_chat_review(prepared=prepared, answer=answer, result=result)
            tracker.report_stream_success(response_length=len(answer))
            yield encode_sse_event("done", result)
        except Exception as exc:
            await session.rollback()
            tracker.report_stream_error()
            finish_span(first_token_span, error=exc)
            yield build_sse_error_payload(
                exc,
                fallback_message="对话生成失败，请稍后重试",
                fallback_code="chat_generation_failed",
                logger=logger,
                log_event="chat.stream_failed",
                conversation_id=prepared.conversation.id,
                error=str(exc),
            )

    return event_stream()


@traced("chat.finalize")
async def _finalize_chat_reply(
    session: AsyncSession,
    *,
    prepared: PreparedChatReply,
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


def _schedule_chat_review(*, prepared: PreparedChatReply, answer: str, result: dict) -> None:
    tracker = AiReviewTracker(operation="chat", route=prepared.route)
    tracker.schedule(
        sample_key=result["messageId"],
        model=prepared.model,
        metadata={
            **prepared.trace_metadata,
            "operation": "chat",
            "message_id": result["messageId"],
        },
        review_payload={
            "question": prepared.user_message.content,
            "route": prepared.route,
            "routeReason": prepared.route_reason,
            "answer": answer,
            "citations": result.get("citations", []),
            "retrievalSnapshot": result.get("retrievalSnapshot", {}),
        },
    )
