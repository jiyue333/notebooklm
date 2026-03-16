"""Stage C – Answer Composer.

Each lane has its own answer protocol per ADR-004 §4.4:
  - article_grounded: evidence-first + anchor citations
  - general:          LLM answer (or fallback when no model configured)
  - recommendation:   1-sentence summary + 3-5 articles + why_similar
  - notebook_research: synthesis + evidence clusters + conflict handling
"""

from __future__ import annotations

import structlog

from app.modules.ai.chat.pipeline.types import (
    ChatInput,
    ChatRoute,
    DraftAnswer,
    RetrievalResult,
    RouteDecision,
)
from app.modules.ai.chat.prompts import ROUTE_BADGES

logger = structlog.get_logger(__name__)


async def compose(
    chat_input: ChatInput,
    decision: RouteDecision,
    retrieval: RetrievalResult,
    *,
    user=None,
) -> DraftAnswer:
    """Build a draft answer following the lane's protocol."""

    route = decision.route
    badge = ROUTE_BADGES.get(route.value, "")

    if route == ChatRoute.ARTICLE_GROUNDED:
        return _compose_article_grounded(chat_input, retrieval, badge)
    if route == ChatRoute.RECOMMENDATION:
        return _compose_recommendation(chat_input, retrieval, badge)
    if route == ChatRoute.NOTEBOOK_RESEARCH:
        return _compose_notebook_research(chat_input, retrieval, badge)

    return await _compose_general(chat_input, badge, user=user)


# ── article_grounded ───────────────────────────────────────────────────────

def _compose_article_grounded(
    inp: ChatInput,
    retrieval: RetrievalResult,
    badge: str,
) -> DraftAnswer:
    chunks = retrieval.evidence_chunks
    if not chunks:
        return DraftAnswer(
            route=ChatRoute.ARTICLE_GROUNDED,
            answer_text="这篇文章中没有找到足够的证据来直接回答这个问题。",
            route_badge=badge,
        )

    evidence_lines = []
    spans = []
    for i, c in enumerate(chunks[:5], 1):
        evidence_lines.append(f"[{i}] {c.text}")
        spans.append({
            "index": i,
            "article_id": c.article_id,
            "chunk_id": c.chunk_id,
            "section_id": c.section_id,
            "text": c.text[:200],
        })

    evidence_text = "\n".join(evidence_lines)
    answer = (
        f"根据当前文章的内容：\n\n"
        f"{evidence_text}\n\n"
        f"基于以上证据，关于「{inp.question}」的回答需要结合上述段落理解。"
    )

    return DraftAnswer(
        route=ChatRoute.ARTICLE_GROUNDED,
        answer_text=answer,
        evidence_spans=spans,
        route_badge=badge,
    )


# ── general ────────────────────────────────────────────────────────────────

async def _compose_general(inp: ChatInput, badge: str, *, user=None) -> DraftAnswer:
    """Use LLM to answer when model is configured; otherwise fallback template."""
    if user:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from app.infra.ai.chat_models import build_user_chat_model

            model = build_user_chat_model(user)
            if model is not None:
                sys = SystemMessage(
                    content="你是一个有帮助的助手。请简洁、直接地回答用户的问题。"
                    "如果问题不明确或无法回答，可以简短说明。用中文回答。"
                )
                msg = HumanMessage(content=inp.question)
                response = await model.ainvoke([sys, msg])
                answer_text = (response.content or "").strip()
                if answer_text:
                    return DraftAnswer(
                        route=ChatRoute.GENERAL,
                        answer_text=answer_text,
                        route_badge=badge,
                    )
        except Exception as e:
            logger.warning("chat.general_llm_failed", error=str(e))

    answer = (
        f"这是一个通用回答，未使用当前笔记本或文章作为证据。\n\n"
        f"关于「{inp.question}」：这需要基于通用知识来回答。\n\n"
        f"如果您希望基于当前文章内容获得更精确的回答，可以尝试重新提问并提及「这篇文章」。"
        f"您也可以在设置中配置模型 API，以获取通用问题的实际回答。"
    )
    return DraftAnswer(
        route=ChatRoute.GENERAL,
        answer_text=answer,
        route_badge=badge,
    )


# ── recommendation ─────────────────────────────────────────────────────────

def _compose_recommendation(
    inp: ChatInput,
    retrieval: RetrievalResult,
    badge: str,
) -> DraftAnswer:
    recs = retrieval.recommended_articles
    if not recs:
        return DraftAnswer(
            route=ChatRoute.RECOMMENDATION,
            answer_text="在您的笔记本中未找到足够相似的文章。",
            route_badge=badge,
        )

    lines = [f"根据您的问题，找到以下相关文章：\n"]
    related = []
    for i, r in enumerate(recs[:5], 1):
        lines.append(f"{i}. **{r.title}**")
        lines.append(f"   相似原因：{r.why_similar}")
        if r.snippet:
            lines.append(f"   摘要：{r.snippet[:120]}...")
        lines.append("")
        related.append({
            "index": i,
            "article_id": r.article_id,
            "title": r.title,
            "notebook_id": r.notebook_id,
            "why_similar": r.why_similar,
            "score": r.score,
        })

    return DraftAnswer(
        route=ChatRoute.RECOMMENDATION,
        answer_text="\n".join(lines),
        related_articles=related,
        route_badge=badge,
    )


# ── notebook_research ──────────────────────────────────────────────────────

def _compose_notebook_research(
    inp: ChatInput,
    retrieval: RetrievalResult,
    badge: str,
) -> DraftAnswer:
    clusters = retrieval.evidence_clusters
    if not clusters:
        return DraftAnswer(
            route=ChatRoute.NOTEBOOK_RESEARCH,
            answer_text="当前笔记本中未找到足够的相关内容来综合回答。",
            route_badge=badge,
        )

    lines = [f"综合当前笔记本中的多篇文章，关于「{inp.question}」：\n"]
    spans = []
    for cluster in clusters[:4]:
        lines.append(f"### {cluster.label}")
        for c in cluster.chunks[:3]:
            lines.append(f"- {c.text[:200]}")
            spans.append({
                "article_id": c.article_id,
                "chunk_id": c.chunk_id,
                "text": c.text[:200],
            })
        lines.append("")

    return DraftAnswer(
        route=ChatRoute.NOTEBOOK_RESEARCH,
        answer_text="\n".join(lines),
        evidence_spans=spans,
        route_badge=badge,
    )
