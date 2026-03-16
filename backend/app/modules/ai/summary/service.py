"""Summary service – the single entry point for article summarisation.

Checks cache, runs the ADR-003 pipeline, persists results.
When output language is Chinese, translates non-Chinese summaries via LLM.
"""

from __future__ import annotations

import hashlib
import json
import re

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.telemetry.metrics import observe_summary_cache_hit
from app.modules.ai.summary.pipeline import run_pipeline
from app.modules.ai.summary.pipeline.observer import SummaryPipelineObserver
from app.modules.ai.summary.pipeline.types import SummaryContext, SummaryInput, SummaryResult
from app.modules.ai.summary.prompts import PROMPT_VERSION
from app.modules.ai.summary import repo

logger = structlog.get_logger(__name__)

# Heuristic: text is likely non-Chinese if ratio of CJK chars is low
_CJK_RATIO_THRESHOLD = 0.15


def _needs_translation_to_chinese(text: str) -> bool:
    if not text or len(text.strip()) < 10:
        return False
    cjk = len(re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]", text))
    return cjk / max(len(text), 1) < _CJK_RATIO_THRESHOLD


async def _translate_to_chinese(text: str, user) -> str:
    """Translate summary to Chinese using user's LLM. Returns original on failure."""
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
        from app.infra.ai.chat_models import build_user_chat_model

        model = build_user_chat_model(user)
        if model is None:
            return text

        sys = SystemMessage(
            content="你是一个专业翻译。将用户提供的学术摘要翻译成简洁流畅的简体中文，保持原意和逻辑结构。只输出译文，不要解释。"
        )
        msg = HumanMessage(content=f"请将以下内容翻译成简体中文：\n\n{text}")
        response = await model.ainvoke([sys, msg])
        out = (response.content or "").strip()
        return out if out else text
    except Exception as e:
        logger.warning("summary.translate_failed", error=str(e))
        return text


async def generate_summary(
    db: AsyncSession,
    *,
    article_id: str,
    notebook_id: str,
    user_id: str,
    title: str,
    clean_markdown: str,
    toc_json: list[dict] | None = None,
    block_graph_json: dict | None = None,
    quality_profile_json: dict | None = None,
    quality_score: float = 0.0,
    language: str = "auto",
    user=None,
) -> SummaryResult:
    """Generate or retrieve a cached summary for an article."""

    content_hash = hashlib.sha256(clean_markdown.encode()).hexdigest()

    # Check DB cache
    cached = await repo.get_cached_summary(
        db,
        article_id=article_id,
        content_hash=content_hash,
        prompt_version=PROMPT_VERSION,
    )
    if cached:
        observe_summary_cache_hit()
        logger.info("summary.cache_hit", article_id=article_id)
        from app.modules.ai.summary.pipeline.types import ArticleSummary, EvidenceSpan, SummaryRoute

        try:
            payload = json.loads(cached.summary_text)
        except (TypeError, json.JSONDecodeError):
            payload = None

        if isinstance(payload, dict):
            route_value = payload.get("route") or SummaryRoute.S.value
            try:
                route = SummaryRoute(route_value)
            except ValueError:
                route = SummaryRoute.S
            evidence_spans = [
                EvidenceSpan(
                    bullet_text=span.get("bulletText") or span.get("bullet_text") or "",
                    block_ids=span.get("blockIds") or span.get("block_ids") or [],
                    role=span.get("role") or "",
                )
                for span in (payload.get("evidenceSpans") or [])
                if isinstance(span, dict)
            ]
            summary_text = payload.get("summaryText") or ""
            if language == "zh" and user and _needs_translation_to_chinese(summary_text):
                summary_text = await _translate_to_chinese(summary_text, user)
            summary = ArticleSummary(
                summary_text=summary_text,
                evidence_spans=evidence_spans,
                profile_tags=payload.get("profileTags") or {},
                confidence=float(payload.get("confidence") or 0),
                prompt_version=payload.get("promptVersion") or cached.prompt_version,
                route=route,
            )
            return SummaryResult(
                summary=summary,
                route=route,
                cache_hit=True,
            )

        summary_text = cached.summary_text
        if language == "zh" and user and _needs_translation_to_chinese(summary_text):
            summary_text = await _translate_to_chinese(summary_text, user)
        return SummaryResult(
            summary=ArticleSummary(
                summary_text=summary_text,
                prompt_version=cached.prompt_version,
                route=SummaryRoute.S,
            ),
            route=SummaryRoute.S,
            cache_hit=True,
        )

    # Run pipeline
    observer = SummaryPipelineObserver()
    ctx = SummaryContext(
        summary_input=SummaryInput(
            article_id=article_id,
            notebook_id=notebook_id,
            user_id=user_id,
            title=title,
            clean_markdown=clean_markdown,
            toc_json=toc_json or [],
            block_graph_json=block_graph_json,
            quality_profile_json=quality_profile_json,
            quality_score=quality_score,
            content_hash=content_hash,
            language=language,
        ),
    )

    result = await run_pipeline(ctx, observer=observer)

    # Translate to Chinese when requested
    if result.summary and result.summary.summary_text and language == "zh" and user:
        if _needs_translation_to_chinese(result.summary.summary_text):
            result.summary.summary_text = await _translate_to_chinese(
                result.summary.summary_text, user
            )

    # Persist to cache
    if result.summary and result.summary.summary_text:
        await repo.save_summary_cache(
            db,
            article_id=article_id,
            content_hash=content_hash,
            prompt_version=PROMPT_VERSION,
            model_provider="heuristic",
            model_name="rule_v1",
            output_language=language,
            summary_text=json.dumps({
                "summaryText": result.summary.summary_text,
                "evidenceSpans": [
                    {
                        "bulletText": span.bullet_text,
                        "blockIds": span.block_ids,
                        "role": span.role,
                    }
                    for span in result.summary.evidence_spans
                ],
                "profileTags": result.summary.profile_tags,
                "confidence": result.summary.confidence,
                "promptVersion": result.summary.prompt_version,
                "route": result.summary.route.value,
            }, ensure_ascii=False),
        )
        await db.commit()

    return result
