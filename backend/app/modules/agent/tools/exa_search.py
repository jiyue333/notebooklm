"""Exa semantic search tool for agents.

Wraps the existing ExaSearchClient so the search agent can call Exa
with per-query parameters (mode, freshness, max_results).
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import tool

from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest

_CONTEXT: dict = {}


def set_exa_context(*, exa_api_key: str) -> None:
    global _CONTEXT
    _CONTEXT = {"exa_api_key": exa_api_key}


@tool
async def exa_search(
    query: str,
    max_results: int = 10,
    mode: str = "auto",
    freshness_hours: int | None = None,
) -> str:
    """Search the web using Exa semantic search engine.

    Best for finding high-quality, relevant web pages, papers, and articles.
    Supports semantic understanding of queries.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (1-20).
        mode: Search mode - "fast", "auto", or "deep".
        freshness_hours: Only return results published within this many hours.
    """
    api_key = _CONTEXT.get("exa_api_key", "")
    if not api_key:
        return json.dumps({"error": "Exa API key not configured"})

    valid_modes = {"fast", "auto", "deep"}
    if mode not in valid_modes:
        mode = "auto"
    max_results = max(1, min(max_results, 20))

    client = ExaSearchClient()
    try:
        request = ExaSearchRequest(
            query=query,
            mode=mode,  # type: ignore[arg-type]
            max_results=max_results,
            freshness_hours=freshness_hours,
        )
        payload = await client.search(request, api_key=api_key)
        results = payload.get("results") or payload.get("data") or []

        items = []
        for r in results[:max_results]:
            items.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("summary") or r.get("description") or "",
                "author": r.get("author"),
                "published_date": r.get("publishedDate"),
                "highlights": (r.get("highlights") or [])[:3],
            })
        return json.dumps(items, ensure_ascii=False, default=str)
    finally:
        await client.close()


@tool
async def exa_find_similar(url: str, max_results: int = 5) -> str:
    """Find web pages similar to a given URL using Exa.

    Useful for expanding search coverage with related content.

    Args:
        url: The reference URL to find similar pages for.
        max_results: Maximum number of similar results to return.
    """
    api_key = _CONTEXT.get("exa_api_key", "")
    if not api_key:
        return json.dumps({"error": "Exa API key not configured"})

    import httpx
    from app.core.config import get_settings

    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.exa_base_url, timeout=20.0) as client:
        resp = await client.post(
            "/findSimilar",
            json={"url": url, "numResults": min(max_results, 10)},
            headers={"x-api-key": api_key, "content-type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results") or []
    items = []
    for r in results:
        items.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("summary") or r.get("description") or "",
        })
    return json.dumps(items, ensure_ascii=False, default=str)
