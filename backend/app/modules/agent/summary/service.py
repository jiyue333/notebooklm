"""Summary service – generates focused article summaries via LLM.

Architecture: check cache → single LLM call → cache result.
No multi-stage pipeline. The prompt adapts to article type automatically.
"""

from __future__ import annotations

import hashlib
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import observe_summary_cache_hit, observe_summary_e2e
from app.modules.agent.summary.prompts import PROMPT_VERSION, SYSTEM_PROMPT, USER_PROMPT
from app.modules.agent.summary import repo

logger = structlog.get_logger(__name__)

_MAX_CONTENT_CHARS = 12000
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
    """Generate or retrieve a cached summary.

    Returns ``{"summary_text": str, "cached": bool}``.
    """

    content_hash = hashlib.sha256(clean_markdown.encode()).hexdigest()

    cached = await repo.get_cached_summary(
        db,
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=PROMPT_VERSION,
    )
    if cached:
        observe_summary_cache_hit()
        text = cached.summary_text
        if language == "zh" and _needs_chinese_translation(text) and user:
            text = await _translate_to_chinese(text, user)
        return {"summary_text": text, "cached": True}

    model = build_user_chat_model(user) if user else None
    if model is None:
        return {"summary_text": "", "cached": False, "error": "model_not_configured"}

    from time import perf_counter
    t0 = perf_counter()

    content = clean_markdown[:_MAX_CONTENT_CHARS]
    system_prompt = SYSTEM_PROMPT
    if language == "zh":
        system_prompt += "\n\nIMPORTANT: Write the summary in 简体中文."

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=USER_PROMPT.format(title=title, content=content)),
    ]

    try:
        response = await model.ainvoke(messages)
        summary_text = (response.content or "").strip()
    except Exception as exc:
        logger.exception("summary.llm_failed", article_id=article_id, error=str(exc))
        return {"summary_text": "", "cached": False, "error": str(exc)[:200]}

    elapsed_ms = round((perf_counter() - t0) * 1000, 2)
    observe_summary_e2e(duration_ms=elapsed_ms)
    logger.info("summary.generated", article_id=article_id, elapsed_ms=elapsed_ms, length=len(summary_text))

    if summary_text:
        model_name = getattr(model, "model_name", "unknown")
        provider = "ollama" if "ollama" in str(type(model)).lower() else "openai"
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
        messages = [
            SystemMessage(content="将以下学术摘要翻译成简洁流畅的简体中文。只输出译文。"),
            HumanMessage(content=text),
        ]
        response = await model.ainvoke(messages)
        return (response.content or "").strip() or text
    except Exception:
        return text
