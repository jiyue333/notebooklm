"""LangGraph agent for intelligent search.

Three-phase pipeline:
  Phase 1: Intent recognition (chat model) – understand query, assign facet weights
  Phase 2: Multi-source recall (ReAct agent + tools) – strategic tool calling
  Phase 3: Scoring & ranking (lite model) – score, deduplicate, rank, build cards
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.modules.agent.search.models import (
    CoverageFacet,
    IntentAnalysis,
    RawSearchItem,
    ScoredItem,
    SearchCardOut,
)
from app.modules.agent.search.prompts import (
    INTENT_SYSTEM_PROMPT,
    INTENT_USER_TEMPLATE,
    PLANNER_SYSTEM_PROMPT,
    SCORER_SYSTEM_PROMPT,
    SCORER_USER_TEMPLATE,
)
from app.modules.agent.tools.exa_search import exa_find_similar, exa_search, set_exa_context
from app.modules.agent.tools.web_search import ddg_news, ddg_search

logger = structlog.get_logger(__name__)

SEARCH_TOOLS = [exa_search, ddg_search, ddg_news, exa_find_similar]


async def run_search_agent(
    chat_model,
    lite_model,
    *,
    query: str,
    exa_api_key: str,
    notebook_title: str = "",
    existing_article_titles: list[str] | None = None,
    existing_article_urls: list[str] | None = None,
    max_results: int = 15,
) -> dict[str, Any]:
    """Run the full 3-phase agent search pipeline.

    Returns:
        {
            "cards": list[dict],          # final ranked search cards
            "intent": dict,               # intent analysis
            "raw_count": int,             # total raw results from tools
            "scored_count": int,          # results after scoring
            "card_count": int,            # final card count
        }
    """
    existing_titles = existing_article_titles or []
    existing_urls = set(existing_article_urls or [])

    set_exa_context(exa_api_key=exa_api_key)

    # ── Phase 1: Intent Recognition ────────────────────────────────────
    intent = await _phase_intent(
        chat_model,
        query=query,
        notebook_title=notebook_title,
        existing_titles=existing_titles,
    )
    logger.info(
        "search_agent.intent_done",
        intent=intent.intent.value,
        domain=intent.domain,
        query_count=len(intent.reformulated_queries),
    )

    # ── Phase 2: Multi-Source Recall (ReAct Agent) ─────────────────────
    raw_items = await _phase_recall(
        chat_model,
        intent=intent,
        query=query,
        notebook_title=notebook_title,
        existing_titles=existing_titles,
    )
    logger.info("search_agent.recall_done", raw_count=len(raw_items))

    if not raw_items:
        return {
            "cards": [],
            "intent": intent.model_dump(),
            "raw_count": 0,
            "scored_count": 0,
            "card_count": 0,
        }

    # ── Dedup by URL ───────────────────────────────────────────────────
    deduped = _deduplicate(raw_items)
    logger.info("search_agent.dedup_done", before=len(raw_items), after=len(deduped))

    # ── Phase 3: Scoring & Ranking ─────────────────────────────────────
    scored = await _phase_score(
        lite_model or chat_model,
        candidates=deduped,
        intent=intent,
        query=query,
        notebook_title=notebook_title,
        existing_titles=existing_titles,
    )
    logger.info("search_agent.score_done", scored_count=len(scored))

    # ── Build final cards ──────────────────────────────────────────────
    cards = _build_cards(scored, existing_urls=existing_urls, max_results=max_results)
    logger.info("search_agent.cards_built", card_count=len(cards))

    return {
        "cards": [c.model_dump() for c in cards],
        "intent": intent.model_dump(),
        "raw_count": len(raw_items),
        "scored_count": len(scored),
        "card_count": len(cards),
    }


# ── Phase 1: Intent Recognition ────────────────────────────────────────────


async def _phase_intent(
    model,
    *,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> IntentAnalysis:
    """Use the chat model to understand intent and reformulate queries."""

    titles_str = ", ".join(existing_titles[:10]) if existing_titles else "(none)"
    user_msg = INTENT_USER_TEMPLATE.format(
        query=query,
        notebook_title=notebook_title or "Untitled",
        article_count=len(existing_titles),
        existing_titles=titles_str,
    )

    try:
        response = await model.ainvoke([
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=user_msg),
        ])
        raw = (response.content or "").strip()
        raw = _strip_json_fences(raw)
        data = json.loads(raw)
        return IntentAnalysis(**data)
    except Exception:
        logger.warning("search_agent.intent_fallback", query=query[:80], exc_info=True)
        return _fallback_intent(query)


def _fallback_intent(query: str) -> IntentAnalysis:
    """Rule-based fallback when LLM intent parsing fails."""
    return IntentAnalysis(
        intent="explore",
        domain="general",
        facet_weights={
            CoverageFacet.OVERVIEW: 0.8,
            CoverageFacet.AUTHORITATIVE: 0.6,
            CoverageFacet.NOVELTY: 0.5,
            CoverageFacet.RECENT: 0.4,
            CoverageFacet.CRITIQUE: 0.3,
            CoverageFacet.IMPLEMENTATION: 0.3,
            CoverageFacet.PRIMARY: 0.3,
        },
        reformulated_queries=[query],
        time_sensitive=False,
    )


# ── Phase 2: Multi-Source Recall ────────────────────────────────────────────


async def _phase_recall(
    model,
    *,
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[RawSearchItem]:
    """Run the ReAct agent with search tools to gather results."""

    titles_str = ", ".join(existing_titles[:8]) if existing_titles else "(none)"
    intent_json = json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str)

    system_prompt = PLANNER_SYSTEM_PROMPT.format(
        notebook_title=notebook_title or "Untitled",
        existing_titles=titles_str,
        intent_json=intent_json,
    )

    agent = create_react_agent(
        model,
        SEARCH_TOOLS,
        prompt=SystemMessage(content=system_prompt),
    )

    result = await agent.ainvoke({
        "messages": [HumanMessage(content=f"Search for: {query}")],
    })

    return _extract_raw_items(result.get("messages", []))


def _extract_raw_items(messages: list) -> list[RawSearchItem]:
    """Extract search results from all ToolMessage payloads."""
    items: list[RawSearchItem] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        content = msg.content or ""
        tool_name = getattr(msg, "name", "") or ""
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            continue

        if isinstance(parsed, dict) and "error" in parsed:
            continue

        result_list = parsed if isinstance(parsed, list) else [parsed]
        for r in result_list:
            if not isinstance(r, dict):
                continue
            url = r.get("url", "").strip()
            if not url:
                continue
            items.append(RawSearchItem(
                title=r.get("title", "").strip() or url,
                url=url,
                description=r.get("description", "").strip(),
                author=r.get("author"),
                published_date=r.get("published_date") or r.get("date"),
                highlights=r.get("highlights", [])[:3],
                source_tool=tool_name,
            ))

    return items


# ── Deduplication ───────────────────────────────────────────────────────────


def _deduplicate(items: list[RawSearchItem]) -> list[RawSearchItem]:
    """Remove duplicate URLs (normalize first)."""
    seen: set[str] = set()
    deduped: list[RawSearchItem] = []
    for item in items:
        key = _normalize_url(item.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip().lower())
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# ── Phase 3: Scoring & Ranking ─────────────────────────────────────────────


async def _phase_score(
    model,
    *,
    candidates: list[RawSearchItem],
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[ScoredItem]:
    """Use the lite model to score and rank candidates."""

    if not candidates:
        return []

    # Batch into chunks of 15 to stay within context limits
    all_scored: list[ScoredItem] = []
    batch_size = 15
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        scored = await _score_batch(
            model,
            batch=batch,
            intent=intent,
            query=query,
            notebook_title=notebook_title,
            existing_titles=existing_titles,
        )
        all_scored.extend(scored)

    all_scored.sort(key=lambda x: x.final_score, reverse=True)
    return all_scored


async def _score_batch(
    model,
    *,
    batch: list[RawSearchItem],
    intent: IntentAnalysis,
    query: str,
    notebook_title: str,
    existing_titles: list[str],
) -> list[ScoredItem]:
    """Score a single batch of candidates."""

    weights_json = json.dumps(
        {k.value: v for k, v in intent.facet_weights.items()},
        ensure_ascii=False,
    )
    candidates_json = json.dumps(
        [c.model_dump() for c in batch],
        ensure_ascii=False,
        default=str,
    )
    titles_str = ", ".join(existing_titles[:8]) if existing_titles else "(none)"

    system = SCORER_SYSTEM_PROMPT.format(facet_weights_json=weights_json)
    user = SCORER_USER_TEMPLATE.format(
        query=query,
        notebook_title=notebook_title or "Untitled",
        existing_titles=titles_str,
        candidates_json=candidates_json,
    )

    try:
        response = await model.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=user),
        ])
        raw = (response.content or "").strip()
        raw = _strip_json_fences(raw)
        data = json.loads(raw)

        if isinstance(data, list):
            return [ScoredItem(**item) for item in data]
        if isinstance(data, dict) and "scored_items" in data:
            return [ScoredItem(**item) for item in data["scored_items"]]
        return []
    except Exception:
        logger.warning("search_agent.score_fallback", exc_info=True)
        return [
            ScoredItem(
                title=c.title,
                url=c.url,
                description=c.description,
                author=c.author,
                published_date=c.published_date,
                highlights=c.highlights,
                source_tool=c.source_tool,
                relevance_score=0.5,
                authority_score=0.3,
                novelty_score=0.5,
                final_score=0.4,
                why_selected="auto-scored (LLM unavailable)",
            )
            for c in batch
        ]


# ── Card Building ───────────────────────────────────────────────────────────


def _build_cards(
    scored: list[ScoredItem],
    *,
    existing_urls: set[str],
    max_results: int,
) -> list[SearchCardOut]:
    """Convert scored items to final frontend cards."""
    cards: list[SearchCardOut] = []

    for rank, item in enumerate(scored[:max_results], start=1):
        url_norm = _normalize_url(item.url)
        is_duplicate = url_norm in {_normalize_url(u) for u in existing_urls}
        domain = urlparse(item.url).netloc

        import_suggestion = "duplicate_risk" if is_duplicate else (
            "recommended" if item.final_score >= 0.6 else "optional"
        )

        authority_badge = None
        if item.authority_score >= 0.8:
            authority_badge = "权威来源"
        elif item.authority_score >= 0.6:
            authority_badge = "知名来源"

        cards.append(SearchCardOut(
            title=item.title,
            url=item.url,
            source_name=domain,
            source_type_badge=_guess_doc_type(item.url, domain),
            published_at=item.published_date,
            authority_badge=authority_badge,
            why_selected=item.why_selected,
            highlights=item.highlights[:2],
            import_suggestion=import_suggestion,
            description=item.description,
            author=item.author,
            final_score=item.final_score,
            display_rank=rank,
        ))

    return cards


def _guess_doc_type(url: str, domain: str) -> str:
    url_lower = url.lower()
    if "arxiv.org" in url_lower:
        return "paper"
    if url_lower.endswith(".pdf"):
        return "pdf"
    if any(d in domain for d in ("github.com", "gitlab.com")):
        return "code"
    if any(d in domain for d in ("docs.", "developer.", "/docs/", "/api/")):
        return "official"
    if any(d in domain for d in (".edu", ".gov", ".ac.")):
        return "academic"
    if "blog" in domain or "medium.com" in domain:
        return "blog"
    if any(d in domain for d in ("news", "reuters", "bbc", "techcrunch")):
        return "news"
    return "web"


def _strip_json_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()
