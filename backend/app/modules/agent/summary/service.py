"""摘要服务：缓存 + LangGraph 编排。"""

from __future__ import annotations

import asyncio
import hashlib
import re
from time import perf_counter
from types import SimpleNamespace
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infra.ai.factory import get_model_identity
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.cache import get_json, set_json, summary_cache_key
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
_SUMMARY_GENERATION_TIMEOUT_SECONDS = 150
_SUMMARY_BACKFILL_LIMIT = 1
_SUMMARY_BACKFILL_TIMEOUT_SECONDS = 30
_TRANSIENT_SUMMARY_ARTICLE_ID = "00000000-0000-0000-0000-000000000001"
_SUMMARY_TEMP_UNAVAILABLE_TEXT = "摘要服务暂时不可用，请 1 分钟后重试。"
_SUMMARY_TEMP_UNAVAILABLE_TTL_SECONDS = 60
_summary_generation_locks: dict[str, asyncio.Lock] = {}
_summary_generation_locks_guard = asyncio.Lock()
_LANGUAGE_ALIASES = {
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "cn": "zh",
    "chinese": "zh",
    "中文": "zh",
    "简体中文": "zh",
    "汉语": "zh",
    "en": "en",
    "en-us": "en",
    "english": "en",
    "英文": "en",
    "英语": "en",
    "auto": "auto",
    "自动": "auto",
}


def normalize_summary_language(language: str | None) -> str:
    raw = (language or "auto").strip()
    if not raw:
        return "auto"
    lowered = raw.lower().replace("_", "-")
    if lowered in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[lowered]
    if raw in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[raw]
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("en"):
        return "en"
    return "auto"


def build_summary_user_snapshot(user):
    if user is None:
        return None
    return SimpleNamespace(
        id=getattr(user, "id", None),
        settings_json={**(getattr(user, "settings_json", None) or {})},
        llm_api_key_ciphertext=getattr(user, "llm_api_key_ciphertext", None),
    )


def _normalize_compare_text(text: str | None) -> str:
    return " ".join(str(text or "").split()).strip().lower()


def _is_unusable_summary(summary_text: str, source_text: str) -> bool:
    summary = _normalize_compare_text(summary_text)
    source = _normalize_compare_text(source_text)
    if not summary:
        return True
    if not source:
        return False

    if summary == source:
        return True

    summary_len = len(summary)
    source_len = len(source)
    if source_len <= 0:
        return False

    if source_len >= 2000 and summary_len >= int(source_len * 0.9):
        return True

    if source_len >= 1500 and summary_len >= int(source_len * 0.75):
        probe = source[: min(1200, source_len)]
        if probe and probe in summary:
            return True

    return False


async def generate_summary(
    db: AsyncSession,
    *,
    article_id: str,
    title: str,
    clean_markdown: str,
    language: str = "auto",
    user=None,
    token_sink=None,
    **_kwargs,
) -> dict:
    """生成摘要，或直接返回缓存摘要。"""
    normalized_language = normalize_summary_language(language)

    # ========== phase 1 检查缓存 ==========
    content_hash = hashlib.sha256(clean_markdown.encode()).hexdigest()

    model = build_user_chat_model(user) if user else None
    provider, model_name = get_model_identity(model) if model else ("unknown", "unknown")
    redis_key = summary_cache_key(
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=PROMPT_VERSION,
        model_provider=provider,
        model_name=str(model_name),
        output_language=normalized_language,
    )
    lock_key = (
        f"{article_id}:{content_hash}:{PROMPT_VERSION}:"
        f"{provider}:{model_name}:{normalized_language}"
    )
    t_lock = perf_counter()
    generation_lock = await _acquire_summary_generation_lock(lock_key)
    await generation_lock.acquire()
    logger.debug(
        "summary.lock_acquired",
        article_id=article_id,
        elapsed_ms=round((perf_counter() - t_lock) * 1000, 2),
    )
    audit_committed = False
    try:
        source_text = clean_markdown or ""
        t_redis = perf_counter()
        redis_cached = await get_json(redis_key)
        logger.debug(
            "summary.redis_cache_check",
            article_id=article_id,
            elapsed_ms=round((perf_counter() - t_redis) * 1000, 2),
            hit=isinstance(redis_cached, dict),
        )
        if isinstance(redis_cached, dict):
            redis_text = str(redis_cached.get("summary_text") or "").strip()
            redis_temp_unavailable = bool(redis_cached.get("temporaryUnavailable"))
            if redis_text and (redis_temp_unavailable or not _is_unusable_summary(redis_text, source_text)):
                observe_summary_cache_hit()
                await _append_summary_audit(
                    db,
                    article_id=article_id,
                    content_hash=content_hash,
                    prompt_version=PROMPT_VERSION,
                    model_provider=provider,
                    model_name=str(model_name),
                    output_language=normalized_language,
                    status="cache_hit",
                    summary_strategy="cache",
                    article_type="general",
                    validation_passed=True,
                    fallback_used=False,
                    fallback_reason="",
                    retry_count=0,
                    summary_length=len(redis_text),
                    latency_ms=0,
                    error_code=None,
                    error_message=None,
                )
                await db.commit()
                audit_committed = True
                return {
                    "summary_text": redis_text,
                    "cached": True,
                    "language": normalized_language,
                    "temporaryUnavailable": redis_temp_unavailable,
                }

        t_db_cache = perf_counter()
        cached = await repo.get_cached_summary(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=PROMPT_VERSION,
            model_provider=provider,
            model_name=str(model_name),
            output_language=normalized_language,
        )
        logger.debug(
            "summary.db_cache_check",
            article_id=article_id,
            elapsed_ms=round((perf_counter() - t_db_cache) * 1000, 2),
            hit=cached is not None,
        )
        if cached:
            text = str(cached.summary_text or "").strip()
            if _is_unusable_summary(text, source_text):
                text = ""
            if text:
                observe_summary_cache_hit()
                await _set_summary_cache(redis_key=redis_key, summary_text=text, language=normalized_language)
                await _append_summary_audit(
                    db,
                    article_id=article_id,
                    content_hash=content_hash,
                    prompt_version=PROMPT_VERSION,
                    model_provider=provider,
                    model_name=str(model_name),
                    output_language=normalized_language,
                    status="cache_hit",
                    summary_strategy="cache",
                    article_type="general",
                    validation_passed=True,
                    fallback_used=False,
                    fallback_reason="",
                    retry_count=0,
                    summary_length=len(text),
                    latency_ms=0,
                    error_code=None,
                    error_message=None,
                )
                await db.commit()
                audit_committed = True
                return {"summary_text": text, "cached": True, "language": normalized_language}

        # zh 请求允许复用任意语言缓存并做翻译（避免重复全链路摘要）
        if normalized_language == "zh":
            t_zh_cache = perf_counter()
            latest_cached = await repo.get_latest_cached_summary(
                db,
                article_id=article_id,
                content_hash=content_hash,
                prompt_version=PROMPT_VERSION,
            )
            logger.debug(
                "summary.zh_latest_cache_check",
                article_id=article_id,
                elapsed_ms=round((perf_counter() - t_zh_cache) * 1000, 2),
                found=latest_cached is not None,
            )
            if latest_cached and str(latest_cached.summary_text or "").strip():
                text = str(latest_cached.summary_text).strip()
                if _needs_chinese_translation(text) and user:
                    t_translate = perf_counter()
                    text = await _translate_to_chinese(text, user)
                    logger.info(
                        "summary.zh_translate_done",
                        article_id=article_id,
                        elapsed_ms=round((perf_counter() - t_translate) * 1000, 2),
                    )
                if not _is_unusable_summary(text, source_text):
                    await _set_summary_cache(redis_key=redis_key, summary_text=text, language=normalized_language)
                    observe_summary_cache_hit()
                    await _append_summary_audit(
                        db,
                        article_id=article_id,
                        content_hash=content_hash,
                        prompt_version=PROMPT_VERSION,
                        model_provider=provider,
                        model_name=str(model_name),
                        output_language=normalized_language,
                        status="cache_hit",
                        summary_strategy="cache_translate",
                        article_type="general",
                        validation_passed=True,
                        fallback_used=False,
                        fallback_reason="",
                        retry_count=0,
                        summary_length=len(text),
                        latency_ms=0,
                        error_code=None,
                        error_message=None,
                    )
                    await db.commit()
                    audit_committed = True
                    return {"summary_text": text, "cached": True, "language": normalized_language}

        # ========== phase 2 执行 LangGraph ==========
        t0 = perf_counter()
        graph = get_summary_graph()
        logger.debug(
            "summary.langgraph_start",
            article_id=article_id,
            language=normalized_language,
            content_chars=len(clean_markdown),
        )

        try:
            result = await asyncio.wait_for(
                graph.ainvoke({
                    "article_id": article_id,
                    "content_hash": content_hash,
                    "title": title,
                    "clean_markdown": clean_markdown,
                    "language": normalized_language,
                    "user": user,
                    "db_session": db,
                    "map_chunks": [],
                    "chunk_summaries": [],
                    "summary_text": "",
                    "compressed_content": "",
                    "compression_cache_hit": False,
                    "article_type": "general",
                    "article_type_confidence": 0.0,
                    "content_stats": {},
                    "model_tier": "standard",
                    "summary_strategy": "direct",
                    "fallback_used": False,
                    "fallback_reason": "",
                    "token_sink": token_sink,
                    "validation_passed": False,
                    "validation_issues": [],
                    "retry_count": 0,
                }),
                timeout=_SUMMARY_GENERATION_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("summary.generate_timeout", article_id=article_id)
            result = {
                "summary_text": "",
                "article_type": "general",
                "validation_passed": False,
                "fallback_used": True,
                "fallback_reason": "summary_timeout",
            }

        article_type = result.get("article_type", "general")
        summary_strategy = str(result.get("summary_strategy", "direct") or "direct")
        retry_count = int(result.get("retry_count", 0) or 0)
        validation_passed = bool(result.get("validation_passed", False))
        fallback_used = bool(result.get("fallback_used", False))
        fallback_reason = str(result.get("fallback_reason", "") or "")
        summary_text = str(result.get("summary_text", "") or "").strip()

        # LLM 阶段已进入 fallback（模型缺失/失败）时，不返回降级正文片段，
        # 统一交给上层使用短时“服务暂不可用”缓存。
        if fallback_used:
            summary_text = ""

        if _is_unusable_summary(summary_text, source_text):
            summary_text = ""
            fallback_used = True
            fallback_reason = "summary_rejected_source_like"

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
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )

        # ========== phase 3 保存缓存 ==========
        if summary_text:
            if article_id != _TRANSIENT_SUMMARY_ARTICLE_ID:
                t_db_save = perf_counter()
                await repo.save_summary_cache(
                    db,
                    article_id=article_id,
                    content_hash=content_hash,
                    prompt_version=PROMPT_VERSION,
                    model_provider=provider,
                    model_name=str(model_name),
                    output_language=normalized_language,
                    summary_text=summary_text,
                )
                await db.commit()
                logger.debug(
                    "summary.db_cache_save",
                    article_id=article_id,
                    elapsed_ms=round((perf_counter() - t_db_save) * 1000, 2),
                )
            t_redis_save = perf_counter()
            await _set_summary_cache(
                redis_key=redis_key,
                summary_text=summary_text,
                language=normalized_language,
            )
            logger.debug(
                "summary.redis_cache_save",
                article_id=article_id,
                elapsed_ms=round((perf_counter() - t_redis_save) * 1000, 2),
            )
        status = "success"
        if fallback_used:
            status = "fallback"
        if not summary_text:
            status = "failed"
        await _append_summary_audit(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=PROMPT_VERSION,
            model_provider=provider,
            model_name=str(model_name),
            output_language=normalized_language,
            status=status,
            summary_strategy=summary_strategy,
            article_type=str(article_type or "general"),
            validation_passed=validation_passed,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retry_count=retry_count,
            summary_length=len(summary_text),
            latency_ms=int(elapsed_ms),
            error_code=fallback_reason or None,
            error_message=None if summary_text else "summary_text_empty",
        )
        await db.commit()
        audit_committed = True

        return {"summary_text": summary_text, "cached": False, "language": normalized_language}
    except Exception as exc:
        await _append_summary_audit(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=PROMPT_VERSION,
            model_provider=provider,
            model_name=str(model_name),
            output_language=normalized_language,
            status="failed",
            summary_strategy="direct",
            article_type="general",
            validation_passed=False,
            fallback_used=False,
            fallback_reason="exception",
            retry_count=0,
            summary_length=0,
            latency_ms=0,
            error_code="summary_exception",
            error_message=str(exc),
        )
        await db.commit()
        audit_committed = True
        raise
    finally:
        if not audit_committed:
            try:
                await db.rollback()
            except Exception:
                logger.debug("summary.audit_rollback_failed", article_id=article_id)
        generation_lock.release()


async def list_notebook_summaries(
    db: AsyncSession,
    *,
    articles: list["Article"],
    user=None,
    language: str = "auto",
    backfill_limit: int = _SUMMARY_BACKFILL_LIMIT,
) -> list[dict]:
    """批量读取 notebook 下文章摘要，并对缺失项做有限回补。"""

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
    normalized_language = normalize_summary_language(language)
    backfilled = 0
    for article in articles:
        if not article.content_hash:
            continue
        source_text = str(article.clean_markdown or "")
        cached = latest_by_article_id.get(article.id)
        summary_text = ""
        if cached is not None and getattr(cached, "content_hash", None) == article.content_hash:
            summary_text = str(getattr(cached, "summary_text", "") or "").strip()
            if _is_unusable_summary(summary_text, source_text):
                summary_text = ""

        if not summary_text and user and backfilled < max(0, backfill_limit) and (article.clean_markdown or "").strip():
            try:
                generated = await asyncio.wait_for(
                    generate_summary(
                        db,
                        article_id=article.id,
                        title=article.title,
                        clean_markdown=article.clean_markdown or "",
                        language=normalized_language,
                        user=user,
                    ),
                    timeout=_SUMMARY_BACKFILL_TIMEOUT_SECONDS,
                )
                summary_text = str(generated.get("summary_text") or "").strip()
                if _is_unusable_summary(summary_text, source_text):
                    summary_text = ""
                backfilled += 1
            except asyncio.TimeoutError:
                logger.warning("summary.backfill_timeout", article_id=article.id)
            except Exception as exc:
                logger.warning(
                    "summary.backfill_failed",
                    article_id=article.id,
                    error=str(exc)[:200],
                )

        if not summary_text:
            continue
        summaries.append({
            "articleId": article.id,
            "title": article.title,
            "summaryText": summary_text,
        })
    return summaries


async def generate_transient_summary(
    db: AsyncSession,
    *,
    title: str,
    clean_markdown: str,
    language: str = "auto",
    user=None,
    token_sink=None,
) -> dict:
    return await generate_summary(
        db,
        article_id=_TRANSIENT_SUMMARY_ARTICLE_ID,
        title=title,
        clean_markdown=clean_markdown,
        language=language,
        user=user,
        token_sink=token_sink,
    )


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


async def _set_summary_cache(*, redis_key: str, summary_text: str, language: str) -> None:
    if not summary_text.strip():
        return
    ttl_seconds = max(3600, int(get_settings().summary_cache_ttl_days) * 24 * 3600)
    await set_json(
        redis_key,
        {
            "summary_text": summary_text,
            "language": language,
        },
        ttl_seconds=ttl_seconds,
    )


async def cache_temporary_unavailable_summary(
    *,
    article_id: str,
    title: str,
    clean_markdown: str,
    language: str = "auto",
    user=None,
) -> str:
    normalized_language = normalize_summary_language(language)
    body = (clean_markdown or "").strip()
    if not body:
        return _SUMMARY_TEMP_UNAVAILABLE_TEXT

    content_hash = hashlib.sha256(body.encode()).hexdigest()
    model = build_user_chat_model(user) if user else None
    provider, model_name = get_model_identity(model) if model else ("unknown", "unknown")
    redis_key = summary_cache_key(
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=PROMPT_VERSION,
        model_provider=provider,
        model_name=str(model_name),
        output_language=normalized_language,
    )
    await set_json(
        redis_key,
        {
            "summary_text": _SUMMARY_TEMP_UNAVAILABLE_TEXT,
            "language": normalized_language,
            "temporaryUnavailable": True,
        },
        ttl_seconds=_SUMMARY_TEMP_UNAVAILABLE_TTL_SECONDS,
    )
    logger.warning(
        "summary.temp_unavailable_cached",
        article_id=article_id,
        title=title,
        language=normalized_language,
        model_provider=provider,
        model_name=str(model_name),
    )
    return _SUMMARY_TEMP_UNAVAILABLE_TEXT


async def _acquire_summary_generation_lock(lock_key: str) -> asyncio.Lock:
    async with _summary_generation_locks_guard:
        lock = _summary_generation_locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            _summary_generation_locks[lock_key] = lock
        return lock


async def _append_summary_audit(
    db: AsyncSession,
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    output_language: str,
    status: str,
    summary_strategy: str,
    article_type: str,
    validation_passed: bool,
    fallback_used: bool,
    fallback_reason: str,
    retry_count: int,
    summary_length: int,
    latency_ms: int,
    error_code: str | None,
    error_message: str | None,
) -> None:
    if article_id == _TRANSIENT_SUMMARY_ARTICLE_ID:
        return
    try:
        await repo.append_generation_audit(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=prompt_version,
            model_provider=model_provider,
            model_name=model_name,
            output_language=output_language,
            status=status,
            summary_strategy=summary_strategy,
            article_type=article_type,
            validation_passed=validation_passed,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retry_count=retry_count,
            summary_length=summary_length,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
        )
    except Exception as exc:
        logger.warning(
            "summary.audit_append_failed",
            article_id=article_id,
            status=status,
            error=str(exc)[:160],
        )


def _build_quick_summary(*, title: str, text: str, language: str) -> str:
    body = (text or "").strip()
    if not body:
        return title or "摘要暂不可用"
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", body) if item.strip()]
    excerpt = "\n\n".join(paragraphs[:3])[:900].strip()
    if language == "zh":
        return f"## {title or '文档摘要'}\n\n{excerpt}".strip()
    return f"## {title or 'Summary'}\n\n{excerpt}".strip()
