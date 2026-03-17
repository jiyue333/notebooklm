"""DuckDuckGo web search tool for agents (free, no API key required).

Uses the ``ddgs`` library as a complementary recall source alongside Exa.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool


@tool
async def ddg_search(query: str, max_results: int = 8, region: str = "wt-wt") -> str:
    """Search the web using DuckDuckGo (free, no API key needed).

    Good for broad web coverage, news, and general queries.
    Use this alongside exa_search for diverse recall.

    Args:
        query: The search query.
        max_results: Maximum number of results (1-20).
        region: Region code for localized results (default: worldwide).
    """
    max_results = max(1, min(max_results, 20))

    import asyncio
    from functools import partial

    from ddgs import DDGS

    def _sync_search() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, region=region, max_results=max_results))

    loop = asyncio.get_running_loop()
    raw_results = await loop.run_in_executor(None, _sync_search)

    items = []
    for r in raw_results:
        items.append({
            "title": r.get("title", ""),
            "url": r.get("href") or r.get("link", ""),
            "description": r.get("body") or r.get("snippet", ""),
        })
    return json.dumps(items, ensure_ascii=False, default=str)


@tool
async def ddg_news(query: str, max_results: int = 5, region: str = "wt-wt") -> str:
    """Search recent news using DuckDuckGo News.

    Ideal for finding the latest news and announcements on a topic.

    Args:
        query: The news search query.
        max_results: Maximum number of results (1-10).
        region: Region code for localized results.
    """
    max_results = max(1, min(max_results, 10))

    import asyncio

    from ddgs import DDGS

    def _sync_news() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.news(query, region=region, max_results=max_results))

    loop = asyncio.get_running_loop()
    raw_results = await loop.run_in_executor(None, _sync_news)

    items = []
    for r in raw_results:
        items.append({
            "title": r.get("title", ""),
            "url": r.get("url") or r.get("link", ""),
            "description": r.get("body", ""),
            "date": r.get("date"),
            "source": r.get("source"),
        })
    return json.dumps(items, ensure_ascii=False, default=str)
