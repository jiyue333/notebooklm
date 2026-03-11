from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import structlog

from app.api.errors import AppError
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai import repo as ai_repo
from app.modules.ai.langchain_factory import (
    build_summary_prompt,
    get_user_generation_settings,
    require_user_chat_model,
)
from app.modules.ai.models import SummaryCache
from app.modules.ai.prompts.summary_prompt import SUMMARY_PROMPT_VERSION
from app.modules.ai.streaming import encode_sse_event, extract_stream_text
from app.modules.search import repo_article

SUMMARY_INPUT_CHAR_LIMIT = 16000

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PreparedSummary:
    user: object
    article: object
    model_settings: dict
    trace_metadata: dict
    cached_item: dict | None
    messages: list | None
    model: object | None


async def get_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
) -> dict:
    prepared = await _prepare_summary(
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

    return await _finalize_summary(session, prepared=prepared, summary=summary)


async def stream_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
):
    prepared = await _prepare_summary(
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

            result = await _finalize_summary(session, prepared=prepared, summary=summary)
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


async def _prepare_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
) -> PreparedSummary:
    article = await repo_article.get_article(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        article_id=article_id,
    )
    if article is None:
        raise AppError(404, "未找到对应文章", code="article_not_found")
    if not article.clean_markdown or not article.content_hash:
        raise AppError(409, "文章正文尚未准备完成", code="article_not_ready")

    model_settings = get_user_generation_settings(user)
    trace_metadata = {
        "user_id": user.id,
        "notebook_id": notebook_id,
        "article_id": article.id,
        "provider": model_settings["modelProvider"],
        "model_name": model_settings["modelName"],
    }
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        article_id=article.id,
        provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
    )
    cached = await ai_repo.get_summary_cache(
        session,
        article_id=article.id,
        content_hash=article.content_hash,
        prompt_version=SUMMARY_PROMPT_VERSION,
        model_provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
        output_language=model_settings["outputLanguage"],
    )
    if cached is not None:
        return PreparedSummary(
            user=user,
            article=article,
            model_settings=model_settings,
            trace_metadata=trace_metadata,
            cached_item={
                "summary": cached.summary_text,
                "cacheHit": True,
                "promptVersion": SUMMARY_PROMPT_VERSION,
            },
            messages=None,
            model=None,
        )

    prompt = build_summary_prompt()
    messages = await prompt.ainvoke(
        {
            "output_language": model_settings["outputLanguage"],
            "title": article.title,
            "content": article.clean_markdown[:SUMMARY_INPUT_CHAR_LIMIT],
        },
        config={"run_name": "summary_prompt", "metadata": trace_metadata},
    )
    return PreparedSummary(
        user=user,
        article=article,
        model_settings=model_settings,
        trace_metadata=trace_metadata,
        cached_item=None,
        messages=messages,
        model=require_user_chat_model(user),
    )


async def _finalize_summary(session, *, prepared: PreparedSummary, summary: str) -> dict:
    await ai_repo.create_summary_cache(
        session,
        SummaryCache(
            user_id=prepared.user.id,
            article_id=prepared.article.id,
            content_hash=prepared.article.content_hash,
            prompt_version=SUMMARY_PROMPT_VERSION,
            model_provider=prepared.model_settings["modelProvider"],
            model_name=prepared.model_settings["modelName"],
            output_language=prepared.model_settings["outputLanguage"],
            summary_text=summary,
        ),
    )
    await session.commit()
    return {
        "summary": summary,
        "cacheHit": False,
        "promptVersion": SUMMARY_PROMPT_VERSION,
    }
