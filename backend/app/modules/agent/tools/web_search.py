"""DuckDuckGo 搜索工具。"""

from __future__ import annotations

from langchain_core.tools import tool


@tool
async def ddg_search(query: str, max_results: int = 8, region: str = "wt-wt") -> list[dict]:
    """用 DuckDuckGo 做网页搜索。"""
    max_results = max(1, min(max_results, 20))

    import asyncio

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
    return items


@tool
async def ddg_news(query: str, max_results: int = 5, region: str = "wt-wt") -> list[dict]:
    """用 DuckDuckGo News 搜索近期新闻。"""
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
    return items
