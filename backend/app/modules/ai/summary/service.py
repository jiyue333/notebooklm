from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from app.api.errors import AppError
from app.api.sse import build_sse_error_payload, encode_sse_event, extract_stream_text
from app.infra.telemetry.tracing import finish_span, start_span, start_span_now
from app.modules.ai.summary.workflow import PreparedSummary, finalize_summary, prepare_summary
from app.modules.tracker import AiReviewTracker, LlmTracker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.auth.models import User

logger = structlog.get_logger(__name__)


async def stream_summary(
    session: AsyncSession,
    *,
    user: User,
    notebook_id: str,
    article_id: str,
):
    tracker = LlmTracker(operation="summary")
    try:
        prepared = await prepare_summary(
            session, user=user, notebook_id=notebook_id, article_id=article_id,
        )
    except Exception:
        tracker.report_request("stream", "error")
        raise

    async def event_stream():
        nonlocal tracker

        if prepared.cached_item is not None:
            tracker.report_request("stream", "cache_hit")
            tracker.report_response_length(len(prepared.cached_item.get("summary", "")))
            yield encode_sse_event("start", {"cacheHit": True})
            yield encode_sse_event("done", prepared.cached_item)
            return

        tracker = LlmTracker.from_model_settings("summary", prepared.model_settings)
        tracker.mark_llm_start()
        assert prepared.model is not None
        first_token_span = start_span_now(
            "summary.model_first_token",
            attributes={
                "provider": tracker.provider,
                "model_name": tracker.model,
            },
        )
        first_token_recorded = False
        summary_parts: list[str] = []
        try:
            yield encode_sse_event("start", {"cacheHit": False})
            with start_span(
                "summary.model_stream",
                attributes={
                    "provider": tracker.provider,
                    "model_name": tracker.model,
                },
            ):
                async for chunk in prepared.model.astream(
                    prepared.messages,
                    config={"run_name": "summary_model", "metadata": prepared.trace_metadata},
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
                    summary_parts.append(text)
                    yield encode_sse_event("token", {"content": text})

            summary = "".join(summary_parts).strip()
            if not summary:
                raise AppError(502, "摘要生成失败", code="summary_generation_failed")

            result = await finalize_summary(session, prepared=prepared, summary=summary)
            _schedule_summary_review(prepared=prepared, summary=summary)
            tracker.report_stream_success(response_length=len(summary))
            yield encode_sse_event("done", result)
        except Exception as exc:
            await session.rollback()
            tracker.report_stream_error()
            finish_span(first_token_span, error=exc)
            yield build_sse_error_payload(
                exc,
                fallback_message="摘要生成失败，请稍后重试",
                fallback_code="summary_generation_failed",
                logger=logger,
                log_event="summary.stream_failed",
                article_id=prepared.article.id,
                error=str(exc),
            )

    return event_stream()


def _schedule_summary_review(*, prepared: PreparedSummary, summary: str) -> None:
    if prepared.model is None:
        return
    tracker = AiReviewTracker(operation="summary", route="summary")
    tracker.schedule(
        sample_key=prepared.article.id,
        model=prepared.model,
        metadata={
            **prepared.trace_metadata,
            "operation": "summary",
            "article_id": prepared.article.id,
        },
        review_payload={
            "title": prepared.article.title,
            "source_excerpt": prepared.article.clean_markdown[:4000],
            "summary": summary,
        },
    )
