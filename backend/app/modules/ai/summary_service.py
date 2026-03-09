from __future__ import annotations

from time import perf_counter

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
from app.modules.search import repo_article

SUMMARY_INPUT_CHAR_LIMIT = 16000


async def get_summary(
    session,
    *,
    user,
    notebook_id: str,
    article_id: str,
) -> dict:
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
        return {
            "summary": cached.summary_text,
            "cacheHit": True,
            "promptVersion": SUMMARY_PROMPT_VERSION,
        }

    prompt = build_summary_prompt()
    model = require_user_chat_model(user)
    messages = await prompt.ainvoke(
        {
            "output_language": model_settings["outputLanguage"],
            "title": article.title,
            "content": article.clean_markdown[:SUMMARY_INPUT_CHAR_LIMIT],
        },
        config={"run_name": "summary_prompt", "metadata": trace_metadata},
    )
    started_at = perf_counter()
    try:
        result = await model.ainvoke(
            messages,
            config={"run_name": "summary_model", "metadata": trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="summary",
            provider=model_settings["modelProvider"],
            model=model_settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    summary, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="summary",
        provider=model_settings["modelProvider"],
        model=model_settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    if not summary:
        raise AppError(502, "摘要生成失败", code="summary_generation_failed")

    await ai_repo.create_summary_cache(
        session,
        SummaryCache(
            user_id=user.id,
            article_id=article.id,
            content_hash=article.content_hash,
            prompt_version=SUMMARY_PROMPT_VERSION,
            model_provider=model_settings["modelProvider"],
            model_name=model_settings["modelName"],
            output_language=model_settings["outputLanguage"],
            summary_text=summary,
        ),
    )
    await session.commit()
    return {
        "summary": summary,
        "cacheHit": False,
        "promptVersion": SUMMARY_PROMPT_VERSION,
    }
