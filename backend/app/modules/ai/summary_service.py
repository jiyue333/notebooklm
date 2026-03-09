from __future__ import annotations

from app.api.errors import AppError
from app.modules.ai import repo as ai_repo
from app.modules.ai.langchain_factory import build_summary_chain, get_user_generation_settings
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

    chain = build_summary_chain(user)
    summary = (
        await chain.ainvoke(
            {
                "output_language": model_settings["outputLanguage"],
                "title": article.title,
                "content": article.clean_markdown[:SUMMARY_INPUT_CHAR_LIMIT],
            }
        )
    ).strip()
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
