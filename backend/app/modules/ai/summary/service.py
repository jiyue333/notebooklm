from __future__ import annotations

from time import perf_counter

import structlog

from app.api.errors import AppError
from app.api.sse import encode_sse_event, extract_stream_text
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai.summary.workflow import finalize_summary, prepare_summary

logger = structlog.get_logger(__name__)


async def get_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
) -> dict:
    prepared = await prepare_summary(
        session,
        user=user,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if prepared.cached_item is not None:
        return prepared.cached_item

    started_at = perf_counter()
    try:
        result = await prepared.model.ainvoke(
            prepared.messages,
            config={"run_name": "summary_model", "metadata": prepared.trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="summary",
            provider=prepared.model_settings["modelProvider"],
            model=prepared.model_settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    summary, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="summary",
        provider=prepared.model_settings["modelProvider"],
        model=prepared.model_settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    if not summary:
        raise AppError(502, "摘要生成失败", code="summary_generation_failed")

    return await finalize_summary(session, prepared=prepared, summary=summary)


async def stream_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
):
    prepared = await prepare_summary(
        session,
        user=user,
        notebook_id=notebook_id,
        article_id=article_id,
    )

    async def event_stream():
        if prepared.cached_item is not None:
            yield encode_sse_event("start", {"cacheHit": True})
            yield encode_sse_event("done", prepared.cached_item)
            return

        started_at = perf_counter()
        summary_parts: list[str] = []
        try:
            yield encode_sse_event("start", {"cacheHit": False})
            async for chunk in prepared.model.astream(
                prepared.messages,
                config={"run_name": "summary_model", "metadata": prepared.trace_metadata},
            ):
                text = extract_stream_text(chunk)
                if not text:
                    continue
                summary_parts.append(text)
                yield encode_sse_event("token", {"content": text})

            summary = "".join(summary_parts).strip()
            observe_llm_call(
                operation="summary",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="success",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            if not summary:
                raise AppError(502, "摘要生成失败", code="summary_generation_failed")

            result = await finalize_summary(session, prepared=prepared, summary=summary)
            yield encode_sse_event("done", result)
        except AppError as exc:
            await session.rollback()
            observe_llm_call(
                operation="summary",
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
                operation="summary",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="error",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            logger.exception(
                "summary.stream_failed",
                article_id=prepared.article.id,
                error=str(exc),
            )
            yield encode_sse_event(
                "error",
                {
                    "message": "摘要生成失败，请稍后重试",
                    "code": "summary_generation_failed",
                    "status": 502,
                    "meta": {},
                },
            )

    return event_stream()
