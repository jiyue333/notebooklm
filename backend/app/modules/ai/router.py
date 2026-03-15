"""AI API endpoints – summary and chat.

POST /notebooks/{id}/ai/events                      – record user event
POST /notebooks/{id}/articles/{aid}/summary/stream   – SSE stream summary
POST /notebooks/{id}/chat/stream                     – SSE stream chat
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user_dep, db_session_dep
from app.api.errors import AppError
from app.api.response import success_response
from app.api.sse import build_sse_error_payload, encode_sse_event
from app.modules.ai.chat.service import send_message
from app.modules.ai.summary.service import generate_summary
from app.modules.notebooks import repo as notebooks_repo

import structlog

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ai"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _normalize_summary_evidence_spans(spans: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for span in spans:
        if hasattr(span, "bullet_text"):
            normalized.append({
                "bulletText": getattr(span, "bullet_text", ""),
                "blockIds": list(getattr(span, "block_ids", []) or []),
                "role": getattr(span, "role", ""),
            })
        elif isinstance(span, dict):
            normalized.append({
                "bulletText": span.get("bulletText") or span.get("bullet_text") or "",
                "blockIds": span.get("blockIds") or span.get("block_ids") or [],
                "role": span.get("role") or "",
            })
    return normalized


def _normalize_chat_evidence_spans(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for span in spans:
        normalized.append({
            "index": span.get("index"),
            "articleId": span.get("articleId") or span.get("article_id"),
            "chunkId": span.get("chunkId") or span.get("chunk_id"),
            "sectionId": span.get("sectionId") or span.get("section_id"),
            "text": span.get("text", ""),
        })
    return normalized


def _normalize_related_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for article in articles:
        normalized.append({
            "index": article.get("index"),
            "articleId": article.get("articleId") or article.get("article_id"),
            "title": article.get("title", ""),
            "notebookId": article.get("notebookId") or article.get("notebook_id"),
            "notebookTitle": article.get("notebookTitle") or article.get("notebook_title"),
            "whySimilar": article.get("whySimilar") or article.get("why_similar", ""),
            "score": article.get("score", 0),
            "snippet": article.get("snippet", ""),
        })
    return normalized


# ── Schemas ────────────────────────────────────────────────────────────────

class AiEventRequest(BaseModel):
    operation: Literal["chat", "summary"]
    action: Literal["follow_up", "citation_open", "answer_copy", "summary_copy"]
    route: str | None = None
    articleId: str | None = None
    conversationId: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    articleId: str | None = None
    message: str = Field(min_length=1)
    readingCursor: dict | None = None
    recentHighlights: list[str] = Field(default_factory=list)
    recentTurns: list[dict[str, str]] = Field(default_factory=list)


# ── AI Events ──────────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/ai/events")
async def ai_event_endpoint(
    notebook_id: str,
    payload: AiEventRequest,
    current_user=Depends(current_user_dep),
):
    logger.info(
        "ai.event.recorded",
        notebook_id=notebook_id,
        user_id=current_user.id,
        operation=payload.operation,
        action=payload.action,
        route=payload.route,
        article_id=payload.articleId,
        conversation_id=payload.conversationId,
    )
    return success_response(item={"accepted": True})


# ── Summary (SSE) ─────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/articles/{article_id}/summary/stream")
async def summary_stream_endpoint(
    notebook_id: str,
    article_id: str,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        try:
            yield encode_sse_event("start", {"articleId": article_id})
            article = await notebooks_repo.get_article(
                session,
                user_id=current_user.id,
                notebook_id=notebook_id,
                article_id=article_id,
            )
            if article is None:
                yield build_sse_error_payload(
                    AppError(404, "未找到对应文章", code="article_not_found"),
                    fallback_message="文章不存在",
                    fallback_code="article_not_found",
                )
                return
            if not article.clean_markdown:
                yield build_sse_error_payload(
                    AppError(422, "文章尚未完成解析", code="article_not_ready"),
                    fallback_message="文章未就绪",
                    fallback_code="article_not_ready",
                )
                return

            result = await generate_summary(
                session,
                article_id=article.id,
                notebook_id=notebook_id,
                user_id=current_user.id,
                title=article.title,
                clean_markdown=article.clean_markdown,
                toc_json=article.toc_json or [],
                block_graph_json=article.block_graph_json,
                quality_profile_json=article.quality_profile_json,
                quality_score=float(article.parse_quality_score or 0),
            )

            summary_text = result.summary.summary_text if result.summary else ""
            yield encode_sse_event("token", {"text": summary_text, "content": summary_text})
            yield encode_sse_event("done", {
                "articleId": article_id,
                "summaryText": summary_text,
                "summary": summary_text,
                "route": result.route.value,
                "confidence": result.summary.confidence if result.summary else 0,
                "promptVersion": result.summary.prompt_version if result.summary else "",
                "cacheHit": result.cache_hit,
                "evidenceSpans": _normalize_summary_evidence_spans(
                    result.summary.evidence_spans if result.summary else [],
                ),
                "profileTags": result.summary.profile_tags if result.summary else {},
            })
        except Exception as exc:
            yield build_sse_error_payload(
                exc,
                fallback_message="摘要生成失败",
                fallback_code="summary_failed",
                logger=logger,
                log_event="ai.summary.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Chat (SSE) ────────────────────────────────────────────────────────────

@router.post("/notebooks/{notebook_id}/chat/stream")
async def chat_stream_endpoint(
    notebook_id: str,
    payload: ChatRequest,
    current_user=Depends(current_user_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    async def _stream() -> AsyncIterator[str]:
        try:
            result = await send_message(
                session,
                user_id=current_user.id,
                notebook_id=notebook_id,
                question=payload.message,
                article_id=payload.articleId,
                conversation_id=payload.conversationId,
                reading_cursor=payload.readingCursor,
                recent_highlights=payload.recentHighlights,
                recent_turns=payload.recentTurns,
            )

            related_articles = _normalize_related_articles(result.related_articles)
            evidence_spans = _normalize_chat_evidence_spans(result.evidence_spans)
            yield encode_sse_event("start", {
                "conversationId": result.conversation_id,
                "articleId": payload.articleId,
            })
            yield encode_sse_event("token", {"text": result.answer_text, "content": result.answer_text})
            yield encode_sse_event("done", {
                "conversationId": result.conversation_id,
                "messageId": result.message_id,
                "route": result.route.value,
                "routeBadge": result.route_badge,
                "answer": result.answer_text,
                "reply": result.answer_text,
                "evidenceSpans": evidence_spans,
                "relatedArticles": related_articles,
                "citations": related_articles,
                "confidence": result.confidence,
                "fallbackUsed": result.fallback_used,
                "fallbackReason": result.fallback_reason,
            })
        except Exception as exc:
            yield build_sse_error_payload(
                exc,
                fallback_message="聊天回复失败",
                fallback_code="chat_failed",
                logger=logger,
                log_event="ai.chat.stream_error",
            )

    return StreamingResponse(_stream(), media_type="text/event-stream", headers=_SSE_HEADERS)
