"""收尾节点：指标观测、响应对象构建与展示字段生成。"""

from __future__ import annotations

from typing import Any

from app.infra.telemetry.metrics import (
    observe_search_authority_proxy,
    observe_search_diversity_proxy,
    observe_search_empty_slate,
    observe_search_novelty_proxy,
    observe_search_stage,
)
from app.modules.agent.search.nodes.recall import _MAX_PROVIDER_CALLS_PER_SEARCH
from app.modules.agent.search.state import (
    SearchGraphState,
    SearchResponsePayload,
    SearchResultCardView,
    SearchRunView,
)
from app.modules.agent.search.utils import _match_preferred_site


async def finalize_node(state: SearchGraphState) -> dict[str, Any]:
    mode = state["mode"]
    selected = state.get("selected_candidates") or state.get("recall_candidates", [])
    top = selected[:10]

    if top:
        authority_count = sum(1 for c in top if c.score_breakdown.get("authority_score", 0) >= 0.8)
        observe_search_authority_proxy(mode=mode, ratio=authority_count / len(top))

        unique_domains = len({c.domain for c in top})
        observe_search_diversity_proxy(mode=mode, entropy=unique_domains / len(top))

        novel_count = sum(1 for c in top if c.score_breakdown.get("novelty_score", 0) >= 0.5)
        observe_search_novelty_proxy(mode=mode, ratio=novel_count / len(top))
    else:
        observe_search_empty_slate(mode=mode, reason="no_above_threshold")

    observe_search_stage(stage="finalize", mode=mode, status="ok", duration_ms=0)
    return {"debug": {
        **state.get("debug", {}),
        "finalCandidateCount": len(state.get("recall_candidates", [])),
        "finalSelectedCount": len(state.get("selected_candidates", [])),
        "providerCallsUsed": int(state.get("provider_calls_used") or 0),
        "providerCallBudget": int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH),
        "providerCallCounts": dict(state.get("provider_call_counts") or {}),
    }}


def _build_response_payload(
    *,
    state: SearchGraphState,
    search_session_id: str,
    elapsed_ms: float,
) -> SearchResponsePayload:
    target_count = state["target_count"]
    candidates = state.get("selected_candidates") or state.get("recall_candidates", [])
    final_candidates = candidates[:target_count]
    items: list[SearchResultCardView] = []
    for idx, candidate in enumerate(final_candidates, start=1):
        preferred_match = _match_preferred_site(candidate.domain, state.get("preferred_sites", []))
        items.append(SearchResultCardView(
            id="",
            title=candidate.title,
            url=candidate.url,
            domain=candidate.domain,
            sourceName=candidate.domain,
            sourceTypeBadge=_source_type_badge(candidate.domain),
            authorityBadge=_authority_badge(candidate.score_breakdown.get("authority_score", 0.0)),
            publishedAt=candidate.published_at,
            description=candidate.description,
            author=candidate.author,
            highlights=candidate.highlights[:2],
            whySelected=candidate.why_selected,
            importSuggestion="duplicate_risk" if candidate.duplicate_risk else ("recommended" if candidate.final_score >= 0.72 else "optional"),
            finalScore=candidate.final_score,
            scoreBreakdown=candidate.score_breakdown,
            provider=candidate.provider,
            queryFamily=candidate.query_key,
            preferredSiteHit=bool(preferred_match or candidate.preferred_site_hit),
            matchedPreferredSite=preferred_match,
            duplicateRisk=candidate.duplicate_risk,
            selectedReasonTags=candidate.selected_reason_tags,
            faviconUrl=f"https://www.google.com/s2/favicons?domain={candidate.domain}&sz=64" if candidate.domain else None,
            displayRank=idx,
        ))
    return SearchResponsePayload(
        run=SearchRunView(
            id=search_session_id,
            notebookId=state["notebook_id"],
            query=state["query"],
            mode=state["mode"],
            modeLabel=_mode_label(state["mode"]),
            status="completed",
            currentRound=state["current_round"],
            maxRounds=state["max_rounds"],
            targetCount=target_count,
            elapsedMs=elapsed_ms,
        ),
        taskSpec=state["task_spec"].model_dump(),
        recallSummary=state.get("recall_summary", {}),
        items=items,
        preferencesApplied={
            "preferredSites": state.get("preferred_sites", []),
        },
        debug=state.get("debug"),
    )


def _mode_label(mode: str) -> str:
    if mode == "fast":
        return "Fast Research"
    if mode == "deep":
        return "Deep Research"
    return "Auto Research"


def _source_type_badge(domain: str) -> str:
    if any(token in domain for token in ["arxiv", "nature", "science", "acm", "springer"]):
        return "Paper"
    if domain.endswith(".gov") or domain.endswith(".edu"):
        return "Official"
    if "docs." in domain or "developer." in domain or "github.com" in domain:
        return "Docs"
    return "Web"


def _authority_badge(score: float) -> str | None:
    if score >= 0.88:
        return "High authority"
    if score >= 0.72:
        return "Trusted"
    return None
