from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.cache import get_json, set_json, summary_cache_key
from app.infra.ai.chat_models import get_user_generation_settings, require_user_chat_model
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_ai_cache_lookup
from app.infra.telemetry.tracing import start_span, traced
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


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

async def prepare_summary(
    session: AsyncSession,
    *,
    user: User,
    notebook_id: str,
    article_id: str,
) -> PreparedSummary:
    with start_span(
        "summary.prepare",
        attributes={"notebook_id": notebook_id, "article_id": article_id},
    ):
        article = await repo_article.get_article(
            session, user_id=user.id, notebook_id=notebook_id, article_id=article_id,
        )
        if article is None:
            raise AppError(404, "未找到对应文章", code="article_not_found")
        if not article.clean_markdown or not article.content_hash:
            raise AppError(409, "文章正文尚未准备完成", code="article_not_ready")

        model_settings = get_user_generation_settings(user)

    trace_metadata = _build_trace_metadata(user, notebook_id, article, model_settings)
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook_id,
        article_id=article.id,
        provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
    )

    # 两级缓存查找（Redis → DB）
    cached_item = await _try_cache_hit(session, article=article, model_settings=model_settings)
    if cached_item is not None:
        return PreparedSummary(
            user=user,
            article=article,
            model_settings=model_settings,
            trace_metadata=trace_metadata,
            cached_item=cached_item,
            messages=None,
            model=None,
        )

    # 缓存未命中 → 构建 prompt
    with start_span(
        "summary.prompt_build",
        attributes={
            "provider": model_settings["modelProvider"],
            "model_name": model_settings["modelName"],
        },
    ):
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


@traced("summary.finalize")
async def finalize_summary(
    session: AsyncSession,
    *,
    prepared: PreparedSummary,
    summary: str,
) -> dict:
    article = prepared.article
    assert article.content_hash is not None, "content_hash must exist at finalize stage"

    await summary_repo.create_summary_cache(
        session,
        SummaryCache(
            user_id=prepared.user.id,
            article_id=article.id,
            content_hash=article.content_hash,
            prompt_version=SUMMARY_PROMPT_VERSION,
            model_provider=prepared.model_settings["modelProvider"],
            model_name=prepared.model_settings["modelName"],
            output_language=prepared.model_settings["outputLanguage"],
            summary_text=summary,
        ),
    )
    await session.commit()
    result = _build_summary_result(summary, cache_hit=False)
    cache_key = _build_cache_key(article, prepared.model_settings)
    await _write_redis_cache(cache_key, summary)
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

@traced("summary.cache_lookup")
async def _try_cache_hit(
    session: AsyncSession,
    *,
    article: Article,
    model_settings: dict,
) -> dict | None:
    """尝试 Redis → DB 两级缓存查找，命中返回 cached_item dict，否则返回 None。"""
    if not article.content_hash:
        return None
    cache_key = _build_cache_key(article, model_settings)

    # 1. Redis
    redis_cached = await get_json(cache_key)
    if isinstance(redis_cached, dict):
        observe_ai_cache_lookup(operation="summary", cache_layer="redis", result="hit")
        return {
            "summary": redis_cached.get("summary", ""),
            "cacheHit": True,
            "promptVersion": redis_cached.get("promptVersion", SUMMARY_PROMPT_VERSION),
        }
    observe_ai_cache_lookup(operation="summary", cache_layer="redis", result="miss")

    # 2. DB
    db_cached = await summary_repo.get_summary_cache(
        session,
        article_id=article.id,
        content_hash=article.content_hash,
        prompt_version=SUMMARY_PROMPT_VERSION,
        model_provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
        output_language=model_settings["outputLanguage"],
    )
    if db_cached is not None:
        observe_ai_cache_lookup(operation="summary", cache_layer="db", result="hit")
        await _write_redis_cache(cache_key, db_cached.summary_text)
        return {
            "summary": db_cached.summary_text,
            "cacheHit": True,
            "promptVersion": SUMMARY_PROMPT_VERSION,
        }
    observe_ai_cache_lookup(operation="summary", cache_layer="db", result="miss")
    return None


def _build_cache_key(article: Article, model_settings: dict) -> str:
    """构造 summary 缓存 key，消除 prepare / finalize 中的重复。"""
    assert article.content_hash is not None
    return summary_cache_key(
        article_id=article.id,
        content_hash=article.content_hash,
        prompt_version=SUMMARY_PROMPT_VERSION,
        model_provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
        output_language=model_settings["outputLanguage"],
    )


async def _write_redis_cache(cache_key: str, summary_text: str) -> None:
    """写入 / 回填 Redis 缓存。"""
    await set_json(
        cache_key,
        {"summary": summary_text, "promptVersion": SUMMARY_PROMPT_VERSION},
        ttl_seconds=get_settings().summary_cache_ttl_days * 24 * 60 * 60,
    )


def _build_summary_result(summary: str, *, cache_hit: bool) -> dict:
    return {
        "summary": summary,
        "cacheHit": cache_hit,
        "promptVersion": SUMMARY_PROMPT_VERSION,
    }


def _build_trace_metadata(
    user: User, notebook_id: str, article: Article, model_settings: dict,
) -> dict:
    return {
        "user_id": user.id,
        "notebook_id": notebook_id,
        "article_id": article.id,
        "provider": model_settings["modelProvider"],
        "model_name": model_settings["modelName"],
    }

