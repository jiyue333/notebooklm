"""Summary pipeline orchestrator – stages A → E."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from app.modules.ai.summary.pipeline.evidence import extract_evidence
from app.modules.ai.summary.pipeline.generator import generate_candidates
from app.modules.ai.summary.pipeline.output import build_output
from app.modules.ai.summary.pipeline.profiler import profile_article
from app.modules.ai.summary.pipeline.route_selector import select_route
from app.modules.ai.summary.pipeline.types import SummaryContext, SummaryResult, SummaryRoute

if TYPE_CHECKING:
    from app.modules.ai.summary.pipeline.observer import SummaryPipelineObserver


class _NullObserver:
    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


async def run_pipeline(
    ctx: SummaryContext,
    observer: SummaryPipelineObserver | None = None,
) -> SummaryResult:
    obs: SummaryPipelineObserver = observer or _NullObserver()  # type: ignore[assignment]
    timings: dict[str, float] = {}
    start = perf_counter()
    inp = ctx.summary_input

    # ── A: Article Profiling ───────────────────────────────────────────
    obs.on_stage_start("profile")
    t0 = perf_counter()
    profile = profile_article(inp)
    ms = _ms(t0)
    timings["profile"] = ms
    obs.on_profiled(profile.article_type.value)
    obs.on_stage_complete("profile", ms, article_type=profile.article_type.value)

    # ── B: Evidence Extraction ─────────────────────────────────────────
    obs.on_stage_start("evidence")
    t0 = perf_counter()
    evidence = extract_evidence(inp, profile)
    ms = _ms(t0)
    timings["evidence"] = ms
    obs.on_evidence_extracted(len(evidence))
    obs.on_stage_complete("evidence", ms, count=len(evidence))

    # ── C: Route Selection ─────────────────────────────────────────────
    obs.on_stage_start("route")
    t0 = perf_counter()
    route = select_route(inp, profile)
    ms = _ms(t0)
    timings["route"] = ms
    obs.on_route_selected(route.value)
    obs.on_stage_complete("route", ms, route=route.value)

    if route == SummaryRoute.X:
        obs.on_fallback_triggered("low_quality_route_x")

    # ── D: Candidate Generation + Judge ────────────────────────────────
    obs.on_stage_start("generate")
    t0 = perf_counter()
    scored = await generate_candidates(
        title=inp.title,
        article_type=profile.article_type.value,
        route=route,
        evidence=evidence,
        clean_markdown=inp.clean_markdown,
        language=inp.language,
    )
    ms = _ms(t0)
    timings["generate"] = ms
    for s in scored:
        obs.on_candidate_generated(s.candidate.style.value)
    obs.on_stage_complete("generate", ms, candidate_count=len(scored))

    if not scored:
        obs.on_fallback_triggered("no_candidates")
        obs.on_pipeline_complete(_ms(start), status="empty")
        return SummaryResult(route=route, elapsed_stages=timings)

    winner = scored[0]
    obs.on_judge_done(winner.candidate.style.value, winner.scores.total)

    # ── E: Final Output ────────────────────────────────────────────────
    obs.on_stage_start("output")
    t0 = perf_counter()
    summary = build_output(winner, profile, evidence, route)
    ms = _ms(t0)
    timings["output"] = ms
    obs.on_finalized()
    obs.on_stage_complete("output", ms)

    total = _ms(start)
    obs.on_pipeline_complete(total, confidence=summary.confidence)

    return SummaryResult(
        summary=summary,
        profile=profile,
        route=route,
        evidence_count=len(evidence),
        candidate_count=len(scored),
        elapsed_stages=timings,
    )


def _ms(t: float) -> float:
    return round((perf_counter() - t) * 1000, 2)
