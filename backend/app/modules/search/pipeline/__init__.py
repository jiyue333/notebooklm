"""Search pipeline orchestrator.

Wires stages A → G into a single ``run_pipeline`` call.  All
observability is delegated to an optional ``SearchPipelineObserver``
so this file contains ZERO metric/logging imports.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from app.modules.search.pipeline.canonicalize import canonicalize
from app.modules.search.pipeline.enrichment import enrich
from app.modules.search.pipeline.query_lattice import generate_lattice
from app.modules.search.pipeline.recall import recall
from app.modules.search.pipeline.scorer import score
from app.modules.search.pipeline.slate_builder import build_slate
from app.modules.search.pipeline.task_parser import parse_task
from app.modules.search.pipeline.types import PipelineContext, PipelineResult

if TYPE_CHECKING:
    from app.modules.search.pipeline.observer import SearchPipelineObserver


class _NullObserver:
    """No-op fallback so callers needn't guard every hook."""

    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


async def run_pipeline(
    ctx: PipelineContext,
    observer: SearchPipelineObserver | None = None,
) -> PipelineResult:
    """Execute the full A → G search pipeline."""

    obs: SearchPipelineObserver = observer or _NullObserver()  # type: ignore[assignment]
    timings: dict[str, float] = {}
    pipeline_start = perf_counter()

    # ── A: Task Parsing ────────────────────────────────────────────────
    obs.on_stage_start("task_parse")
    t0 = perf_counter()
    task_spec = parse_task(ctx.user_query, ctx.notebook)
    ms = _elapsed_ms(t0)
    timings["task_parse"] = ms
    obs.on_stage_complete(
        "task_parse", ms,
        intent=task_spec.intent.value,
        domain=task_spec.domain,
        facets=[f.value for f in task_spec.coverage_facets],
    )

    # ── B: Query Lattice ───────────────────────────────────────────────
    obs.on_stage_start("query_lattice")
    t0 = perf_counter()
    families = generate_lattice(
        task_spec,
        ctx.user_query,
        search_mode=ctx.search_mode,
        notebook=ctx.notebook,
        freshness_hours=ctx.freshness_hours,
    )
    ms = _elapsed_ms(t0)
    timings["query_lattice"] = ms
    obs.on_stage_complete(
        "query_lattice", ms,
        family_count=len(families),
        roles=[f.role.value for f in families],
    )

    # ── C: Multi-Source Recall ─────────────────────────────────────────
    obs.on_stage_start("recall", family_count=len(families))
    t0 = perf_counter()
    raw_candidates = await recall(
        families,
        exa_api_key=ctx.exa_api_key,
        search_mode=ctx.search_mode,
        expected_source_mix=task_spec.expected_source_mix,
    )
    ms = _elapsed_ms(t0)
    timings["recall"] = ms
    obs.on_stage_complete("recall", ms, raw_count=len(raw_candidates))

    if not raw_candidates:
        obs.on_empty_slate(reason="no_recall_results")
        obs.on_pipeline_complete(_elapsed_ms(pipeline_start), card_count=0)
        return PipelineResult(
            cards=[],
            task_spec=task_spec,
            query_families=families,
            raw_candidate_count=0,
            elapsed_stages=timings,
        )

    # ── D: Canonicalize & Dedup ────────────────────────────────────────
    obs.on_stage_start("canonicalize")
    t0 = perf_counter()
    canonical = canonicalize(raw_candidates)
    ms = _elapsed_ms(t0)
    timings["canonicalize"] = ms
    obs.on_dedup(before=len(raw_candidates), after=len(canonical))
    obs.on_stage_complete("canonicalize", ms, before=len(raw_candidates), after=len(canonical))

    # ── E: Enrichment ──────────────────────────────────────────────────
    obs.on_stage_start("enrichment")
    t0 = perf_counter()
    enriched = enrich(canonical)
    ms = _elapsed_ms(t0)
    timings["enrichment"] = ms
    obs.on_stage_complete("enrichment", ms, count=len(enriched))

    # ── F: Scoring ─────────────────────────────────────────────────────
    obs.on_stage_start("rerank")
    t0 = perf_counter()
    scored = score(enriched, task_spec, ctx.notebook)
    ms = _elapsed_ms(t0)
    timings["rerank"] = ms
    obs.on_stage_complete("rerank", ms, count=len(scored))

    # ── G: Slate Building ──────────────────────────────────────────────
    obs.on_stage_start("slate_build")
    t0 = perf_counter()
    cards = build_slate(
        scored,
        task_spec,
        ctx.notebook,
        ctx.search_mode,
        ctx.max_results,
    )
    ms = _elapsed_ms(t0)
    timings["slate_build"] = ms
    obs.on_stage_complete("slate_build", ms, card_count=len(cards))

    if not cards:
        obs.on_empty_slate(reason="slate_empty_after_build")

    # ── post-pipeline quality signals ──────────────────────────────────
    total_ms = _elapsed_ms(pipeline_start)
    obs.on_slate_quality(cards)
    obs.on_pipeline_complete(total_ms, card_count=len(cards))

    return PipelineResult(
        cards=cards,
        task_spec=task_spec,
        query_families=families,
        raw_candidate_count=len(raw_candidates),
        canonical_candidate_count=len(canonical),
        enriched_candidate_count=len(enriched),
        elapsed_stages=timings,
    )


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
