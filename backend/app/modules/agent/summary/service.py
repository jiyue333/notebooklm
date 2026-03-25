"""摘要服务：缓存 + LangGraph 编排。"""

from __future__ import annotations

import hashlib
import re
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.factory import get_model_identity
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import (
    observe_summary_cache_hit,
    observe_summary_e2e,
    observe_summary_route_mix,
)
from app.modules.agent.summary.graph import get_summary_graph
from app.modules.agent.summary.prompts import PROMPT_VERSION
from app.modules.agent.summary import repo

if TYPE_CHECKING:
    from app.modules.notebooks.models import Article

logger = structlog.get_logger(__name__)

_CJK_RATIO_THRESHOLD = 0.15


async def generate_summary(
    db: AsyncSession,
    *,
    article_id: str,
    title: str,
    clean_markdown: str,
    language: str = "auto",
    user=None,
    **_kwargs,
) -> dict:
    """生成摘要，或直接返回缓存摘要。"""

    # ========== phase 1 检查缓存 ==========
    content_hash = hashlib.sha256(clean_markdown.encode()).hexdigest()

    model = build_user_chat_model(user) if user else None
    provider, model_name = get_model_identity(model) if model else ("unknown", "unknown")
    cached = await repo.get_cached_summary(
        db,
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=PROMPT_VERSION,
        model_provider=provider,
        model_name=str(model_name),
        output_language=language,
    )
    if cached:
        observe_summary_cache_hit()
        text = cached.summary_text
        if language == "zh" and _needs_chinese_translation(text) and user:
            text = await _translate_to_chinese(text, user)
        return {"summary_text": text, "cached": True}

    # ========== phase 2 执行 LangGraph ==========
    t0 = perf_counter()
    graph = get_summary_graph()

    result = await graph.ainvoke({
        "article_id": article_id,
        "title": title,
        "clean_markdown": clean_markdown,
        "language": language,
        "user": user,
        "map_chunks": [],
        "chunk_summaries": [],
        "summary_text": "",
        "compressed_content": "",
        "article_type": "general",
        "content_stats": {},
        "model_tier": "standard",
        "validation_passed": False,
        "validation_issues": [],
        "retry_count": 0,
    })

    summary_text = result.get("summary_text", "")
    article_type = result.get("article_type", "general")

    elapsed_ms = round((perf_counter() - t0) * 1000, 2)
    observe_summary_e2e(duration_ms=elapsed_ms)
    observe_summary_route_mix(route=article_type)
    logger.info(
        "summary.generated",
        article_id=article_id,
        article_type=article_type,
        elapsed_ms=elapsed_ms,
        length=len(summary_text),
        validated=result.get("validation_passed", False),
    )

    # ========== phase 3 保存缓存 ==========
    if summary_text:
        await repo.save_summary_cache(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=PROMPT_VERSION,
            model_provider=provider,
            model_name=str(model_name),
            output_language=language,
            summary_text=summary_text,
        )
        await db.commit()

    return {"summary_text": summary_text, "cached": False}


async def list_notebook_summaries(
    db: AsyncSession,
    *,
    articles: list["Article"],
) -> list[dict]:
    """批量读取 notebook 下文章的摘要缓存，不触发生成。"""

    article_ids = [article.id for article in articles]
    cached_rows = await repo.list_cached_summaries_by_article_ids(
        db,
        article_ids=article_ids,
        prompt_version=PROMPT_VERSION,
    )

    latest_by_article_id: dict[str, object] = {}
    for row in cached_rows:
        latest_by_article_id.setdefault(row.article_id, row)

    summaries: list[dict] = []
    for article in articles:
        if not article.content_hash:
            continue
        cached = latest_by_article_id.get(article.id)
        if cached is None or getattr(cached, "content_hash", None) != article.content_hash:
            continue
        summary_text = getattr(cached, "summary_text", "").strip()
        if not summary_text:
            continue
        summaries.append({
            "articleId": article.id,
            "title": article.title,
            "summaryText": summary_text,
        })
    return summaries


def _needs_chinese_translation(text: str) -> bool:
    if not text or len(text.strip()) < 10:
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    return cjk / max(len(text), 1) < _CJK_RATIO_THRESHOLD


async def _translate_to_chinese(text: str, user) -> str:
    try:
        model = build_user_chat_model(user)
        if model is None:
            return text
        from langchain_core.messages import HumanMessage, SystemMessage
        messages = [
            SystemMessage(content="将以下学术摘要翻译成简洁流畅的简体中文。只输出译文。"),
            HumanMessage(content=text),
        ]
        response = await model.ainvoke(messages)
        return (response.content or "").strip() or text
    except Exception:
        return text
