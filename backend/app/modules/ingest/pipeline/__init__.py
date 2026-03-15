"""Ingest pipeline orchestrator.

Wires stages A → I into a single ``run_pipeline`` call.  All
observability is delegated to an optional ``IngestPipelineObserver``.
"""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from app.modules.ingest.pipeline.block_graph import build_block_graph
from app.modules.ingest.pipeline.canonicalize import canonicalize
from app.modules.ingest.pipeline.doc_router import route_document
from app.modules.ingest.pipeline.fetch import fetch
from app.modules.ingest.pipeline.fusion import fuse
from app.modules.ingest.pipeline.indexer import build_chunks, embed_chunks
from app.modules.ingest.pipeline.parse import generate_parse_candidates
from app.modules.ingest.pipeline.quality_judge import judge_candidates
from app.modules.ingest.pipeline.toc_builder import build_toc
from app.modules.ingest.pipeline.types import IngestContext, IngestResult

if TYPE_CHECKING:
    from app.modules.ingest.pipeline.observer import IngestPipelineObserver


class _NullObserver:
    def __getattr__(self, _name):
        return lambda *_a, **_kw: None


async def run_pipeline(
    ctx: IngestContext,
    observer: IngestPipelineObserver | None = None,
) -> IngestResult:
    """Execute the full A → I ingest pipeline."""

    obs: IngestPipelineObserver = observer or _NullObserver()  # type: ignore[assignment]
    timings: dict[str, float] = {}
    pipeline_start = perf_counter()

    # ── A: Fetch & Fingerprint ─────────────────────────────────────────
    obs.on_stage_start("fetch")
    t0 = perf_counter()
    artifact = await fetch(ctx.ingest_input)
    ms = _elapsed_ms(t0)
    timings["fetch"] = ms
    obs.on_fetch_complete(ms, artifact.content_type)
    obs.on_stage_complete("fetch", ms, size_bytes=artifact.size_bytes)

    # ── B: Canonicalize & Dedup ────────────────────────────────────────
    obs.on_stage_start("canonicalize")
    t0 = perf_counter()
    canonical = canonicalize(artifact, ctx.existing_dedupe_keys)
    ms = _elapsed_ms(t0)
    timings["canonicalize"] = ms
    obs.on_stage_complete("canonicalize", ms, is_duplicate=canonical.is_duplicate)

    if canonical.is_duplicate:
        obs.on_pipeline_complete(
            _elapsed_ms(pipeline_start), is_duplicate=True,
        )
        return IngestResult(
            is_duplicate=True,
            duplicate_article_id=canonical.duplicate_article_id,
            elapsed_stages=timings,
        )

    # ── C: Document Type Router ────────────────────────────────────────
    obs.on_stage_start("doc_route")
    t0 = perf_counter()
    route = route_document(canonical)
    ms = _elapsed_ms(t0)
    timings["doc_route"] = ms
    obs.on_type_routed(route.category.value)
    obs.on_stage_complete("doc_route", ms, category=route.category.value)

    # ── D: Multi-Parser Candidates ─────────────────────────────────────
    obs.on_stage_start("parse")
    t0 = perf_counter()
    candidates = await generate_parse_candidates(
        canonical, route, exa_api_key=ctx.exa_api_key,
    )
    ms = _elapsed_ms(t0)
    timings["parse"] = ms
    for c in candidates:
        obs.on_parse_candidate_generated(c.parser_name, bool(c.markdown))
    obs.on_stage_complete("parse", ms, candidate_count=len(candidates))

    if not candidates:
        obs.on_fallback_triggered("no_parse_candidates")
        obs.on_pipeline_complete(_elapsed_ms(pipeline_start), card_count=0)
        return IngestResult(
            doc_route=route,
            parse_candidate_count=0,
            elapsed_stages=timings,
        )

    # ── E: Quality Judge ───────────────────────────────────────────────
    obs.on_stage_start("quality_judge")
    t0 = perf_counter()
    scored = judge_candidates(candidates)
    ms = _elapsed_ms(t0)
    timings["quality_judge"] = ms
    for s in scored:
        obs.on_parse_scored(s.candidate.parser_name, s.quality.total)
    best = scored[0]
    obs.on_parse_selected(best.candidate.parser_name, best.quality.total)
    obs.on_stage_complete("quality_judge", ms, best_score=best.quality.total)

    if best.needs_llm_fallback:
        obs.on_fallback_triggered("low_quality_score")

    # ── F: Fusion & Repair ─────────────────────────────────────────────
    obs.on_stage_start("fusion")
    t0 = perf_counter()
    fused = fuse(scored)
    ms = _elapsed_ms(t0)
    timings["fusion"] = ms
    obs.on_stage_complete("fusion", ms, word_count=fused.word_count)

    # ── G: TOC Generation ──────────────────────────────────────────────
    obs.on_stage_start("toc")
    t0 = perf_counter()
    toc = build_toc(fused)
    ms = _elapsed_ms(t0)
    timings["toc"] = ms
    is_synthetic = any(n.is_synthetic for n in toc)
    obs.on_toc_generated(len(toc), is_synthetic)
    obs.on_anchor_bound(len(toc))
    obs.on_stage_complete("toc", ms, node_count=len(toc))

    # ── H: BlockGraph ──────────────────────────────────────────────────
    obs.on_stage_start("block_graph")
    t0 = perf_counter()
    graph = build_block_graph(fused, toc)
    ms = _elapsed_ms(t0)
    timings["block_graph"] = ms
    obs.on_block_graph_built(graph.block_type_counts)
    obs.on_stage_complete("block_graph", ms, block_count=len(graph.blocks))

    # ── I: Chunk & Embed ───────────────────────────────────────────────
    obs.on_stage_start("index")
    t0 = perf_counter()
    chunks = build_chunks(graph)
    chunks = await embed_chunks(chunks)
    ms = _elapsed_ms(t0)
    timings["index"] = ms
    obs.on_stage_complete("index", ms, chunk_count=len(chunks))

    # ── done ───────────────────────────────────────────────────────────
    total_ms = _elapsed_ms(pipeline_start)
    obs.on_pipeline_complete(
        total_ms,
        quality_score=fused.quality_score,
        chunk_count=len(chunks),
        toc_count=len(toc),
        block_count=len(graph.blocks),
    )

    return IngestResult(
        fused_doc=fused,
        toc=toc,
        block_graph=graph,
        chunks=chunks,
        doc_route=route,
        parse_candidate_count=len(candidates),
        primary_parser=fused.primary_parser,
        quality_score=fused.quality_score,
        elapsed_stages=timings,
    )


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
