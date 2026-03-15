"""Chat pipeline orchestrator – stages A → D."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from app.modules.ai.chat.pipeline.composer import compose
from app.modules.ai.chat.pipeline.scope_router import route
from app.modules.ai.chat.pipeline.types import ChatContext, ChatResult
from app.modules.ai.chat.pipeline.verifier import verify

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.modules.ai.chat.pipeline.observer import ChatPipelineObserver


class _NullObserver:
    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


async def run_pipeline(
    ctx: ChatContext,
    db: "AsyncSession",
    observer: "ChatPipelineObserver | None" = None,
) -> ChatResult:
    obs: ChatPipelineObserver = observer or _NullObserver()  # type: ignore[assignment]
    timings: dict[str, float] = {}
    start = perf_counter()
    inp = ctx.chat_input

    # ── A: Scope Router ────────────────────────────────────────────────
    obs.on_stage_start("route")
    t0 = perf_counter()
    decision = route(inp)
    ms = _ms(t0)
    timings["route"] = ms
    obs.on_route_selected(decision.route.value, decision.confidence)
    obs.on_stage_complete("route", ms, route=decision.route.value)

    # ── B: Retrieval ───────────────────────────────────────────────────
    from app.modules.ai.chat.pipeline.retriever import retrieve

    obs.on_stage_start("retrieval")
    t0 = perf_counter()
    retrieval_result = await retrieve(db, inp, decision)
    ms = _ms(t0)
    timings["retrieval"] = ms
    obs.on_retrieval_done(
        evidence_count=len(retrieval_result.evidence_chunks),
        recommendation_count=len(retrieval_result.recommended_articles),
    )
    obs.on_stage_complete("retrieval", ms)

    # ── C: Compose ─────────────────────────────────────────────────────
    obs.on_stage_start("compose")
    t0 = perf_counter()
    draft = compose(inp, decision, retrieval_result)
    ms = _ms(t0)
    timings["compose"] = ms
    obs.on_answer_generated()
    obs.on_stage_complete("compose", ms)

    # ── D: Verify ──────────────────────────────────────────────────────
    obs.on_stage_start("verify")
    t0 = perf_counter()
    verified = verify(draft, decision, retrieval_result)
    ms = _ms(t0)
    timings["verify"] = ms
    obs.on_verified(verified.is_verified, verified.evidence_coverage)
    if verified.fallback_used:
        obs.on_fallback_triggered(verified.fallback_reason.value)
    obs.on_stage_complete("verify", ms)

    # ── done ───────────────────────────────────────────────────────────
    total = _ms(start)
    obs.on_response_served()
    obs.on_pipeline_complete(total)

    return ChatResult(
        route=decision.route,
        answer_text=verified.answer.answer_text,
        evidence_spans=verified.answer.evidence_spans,
        related_articles=verified.answer.related_articles,
        route_badge=verified.answer.route_badge,
        confidence=verified.confidence,
        fallback_used=verified.fallback_used,
        fallback_reason=verified.fallback_reason.value if verified.fallback_used else "",
        elapsed_stages=timings,
    )


def _ms(t: float) -> float:
    return round((perf_counter() - t) * 1000, 2)
