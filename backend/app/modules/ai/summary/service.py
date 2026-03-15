"""Summary service – the single entry point for article summarisation.

Checks cache, runs the ADR-003 pipeline, persists results.
"""

from __future__ import annotations

import hashlib
import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.summary.pipeline import run_pipeline
from app.modules.ai.summary.pipeline.observer import SummaryPipelineObserver
from app.modules.ai.summary.pipeline.types import SummaryContext, SummaryInput, SummaryResult
from app.modules.ai.summary.prompts import PROMPT_VERSION
from app.modules.ai.summary import repo

logger = structlog.get_logger(__name__)


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
            summary = ArticleSummary(
                summary_text=payload.get("summaryText") or "",
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

        return SummaryResult(
            summary=ArticleSummary(
                summary_text=cached.summary_text,
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
