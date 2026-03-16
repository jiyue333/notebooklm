"""Search pipeline orchestrator.

Wires stages A → G into a single ``run_pipeline`` call.  All
observability is delegated to an optional ``SearchPipelineObserver``
so this file contains ZERO metric/logging imports.

Fallback logic (ADR-001 §4.10):
  - Too few results after recall  → relax freshness, broaden queries
  - Too much dedup after canon.   → diversity expansion via extra queries
  - Engine partial failure         → continue with surviving routes
  - Empty slate after build        → retry with relaxed constraints
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
from app.modules.search.pipeline.task_parser import parse_task, parse_task_llm
from app.modules.search.pipeline.types import (
    CoverageFacet,
    PipelineContext,
    PipelineResult,
    QueryFamily,
    QueryRole,
    TaskSpec,
)

if TYPE_CHECKING:
    from app.modules.search.pipeline.observer import SearchPipelineObserver

_RECALL_TOO_FEW = 5
_DEDUP_HIGH_RATIO = 0.70
_SLATE_TOO_FEW = 3


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
    use_llm = False
    try:
        from app.core.config import get_settings
        use_llm = get_settings().search_use_llm_task_parser
    except Exception:
        pass
    if use_llm:
        task_spec = await parse_task_llm(ctx.user_query, ctx.notebook)
    else:
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

    # ── Fallback: too few recall results → relax & retry ──────────────
    if 0 < len(raw_candidates) < _RECALL_TOO_FEW:
        obs.on_stage_start("fallback_recall_relax")
        t0 = perf_counter()
        relaxed = _build_relaxed_families(ctx.user_query, families)
        extra = await recall(
            relaxed,
            exa_api_key=ctx.exa_api_key,
            search_mode=ctx.search_mode,
            expected_source_mix=task_spec.expected_source_mix,
        )
        raw_candidates.extend(extra)
        ms = _elapsed_ms(t0)
        timings["fallback_recall_relax"] = ms
        obs.on_stage_complete(
            "fallback_recall_relax", ms,
            reason="too_few_results",
            extra_count=len(extra),
        )

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

    # ── Fallback: high dedup ratio → diversity expansion ──────────────
    if len(raw_candidates) > 0:
        dedup_ratio = 1.0 - len(canonical) / len(raw_candidates)
        if dedup_ratio > _DEDUP_HIGH_RATIO and len(canonical) < _RECALL_TOO_FEW:
            obs.on_stage_start("fallback_diversity_expand")
            t0 = perf_counter()
            diverse_families = _build_diversity_families(ctx.user_query, task_spec)
            extra = await recall(
                diverse_families,
                exa_api_key=ctx.exa_api_key,
                search_mode=ctx.search_mode,
                expected_source_mix=task_spec.expected_source_mix,
            )
            if extra:
                all_raw = raw_candidates + extra
                canonical = canonicalize(all_raw)
                raw_candidates = all_raw
            ms = _elapsed_ms(t0)
            timings["fallback_diversity_expand"] = ms
            obs.on_stage_complete(
                "fallback_diversity_expand", ms,
                reason="high_dedup_ratio",
                dedup_ratio=round(dedup_ratio, 2),
                extra_count=len(extra),
            )

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

    # ── Fallback: empty/thin slate → retry with relaxed constraints ───
    if len(cards) < _SLATE_TOO_FEW and scored:
        obs.on_stage_start("fallback_slate_relax")
        t0 = perf_counter()
        cards = build_slate(
            scored,
            task_spec,
            ctx.notebook,
            "deep",
            max(ctx.max_results, 20),
        )
        ms = _elapsed_ms(t0)
        timings["fallback_slate_relax"] = ms
        obs.on_stage_complete(
            "fallback_slate_relax", ms,
            reason="thin_slate",
            card_count=len(cards),
        )

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


# ---------------------------------------------------------------------------
# Fallback helpers
# ---------------------------------------------------------------------------

def _build_relaxed_families(
    user_query: str,
    original_families: list[QueryFamily],
) -> list[QueryFamily]:
    """Broaden the search: drop freshness filters, add a generic query."""
    relaxed: list[QueryFamily] = []
    for f in original_families[:2]:
        relaxed.append(QueryFamily(
            role=f.role,
            query_text=f.query_text,
            max_results=f.max_results,
            freshness_hours=None,
        ))
    relaxed.append(QueryFamily(
        role=QueryRole.CANONICAL,
        query_text=user_query.strip(),
        max_results=12,
        freshness_hours=None,
    ))
    return relaxed


def _build_diversity_families(
    user_query: str,
    task: TaskSpec,
) -> list[QueryFamily]:
    """Generate extra queries targeting under-represented facets."""
    _FACET_SUFFIX = {
        CoverageFacet.CRITIQUE: "limitations challenges risks evaluation",
        CoverageFacet.IMPLEMENTATION: "architecture implementation case study tutorial",
        CoverageFacet.RECENT: "latest 2025 2026 new developments",
    }
    _FACET_ROLE = {
        CoverageFacet.CRITIQUE: QueryRole.CRITICAL,
        CoverageFacet.IMPLEMENTATION: QueryRole.IMPLEMENTATION,
        CoverageFacet.RECENT: QueryRole.RECENT,
    }
    families: list[QueryFamily] = []
    for facet in (CoverageFacet.CRITIQUE, CoverageFacet.IMPLEMENTATION, CoverageFacet.RECENT):
        suffix = _FACET_SUFFIX.get(facet, "")
        role = _FACET_ROLE.get(facet, QueryRole.CANONICAL)
        families.append(QueryFamily(
            role=role,
            query_text=f"{user_query.strip()} {suffix}",
            max_results=6,
            freshness_hours=None,
        ))
    return families


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
