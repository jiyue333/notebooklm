from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.api.errors import AppError
from app.infra.ai.chat_models import get_user_generation_settings, require_user_chat_model
from app.infra.telemetry.context import bind_observability_context
from app.modules.ai.summary import repo as summary_repo
from app.modules.ai.summary.models import SummaryCache
from app.modules.ai.prompts.summary_prompt import SUMMARY_PROMPT_VERSION, build_summary_prompt
from app.modules.search.articles import repo as repo_article

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notebooks.models import Article

SUMMARY_INPUT_CHAR_LIMIT = 16000


@dataclass(slots=True)
class PreparedSummary:
    user: User
    article: Article
    model_settings: dict
    trace_metadata: dict
    cached_item: dict | None
    messages: Any | None
    model: Any | None


async def prepare_summary(
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
    cached = await summary_repo.get_summary_cache(
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


async def finalize_summary(session, *, prepared: PreparedSummary, summary: str) -> dict:
    await summary_repo.create_summary_cache(
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
