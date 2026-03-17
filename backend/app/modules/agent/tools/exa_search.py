"""Exa 搜索工具。"""

from __future__ import annotations

from langchain_core.tools import tool

from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest

@tool
async def exa_search(
    query: str,
    exa_api_key: str,
    exa_mode: str = "auto",
    max_results: int = 10,
    freshness_hours: int | None = None,
) -> list[dict]:
    """用 Exa 做语义搜索。"""
    if not exa_api_key:
        return []

    valid_modes = {"fast", "auto", "deep"}
    mode = exa_mode if exa_mode in valid_modes else "auto"
    max_results = max(1, min(max_results, 20))

    client = ExaSearchClient()
    try:
        request = ExaSearchRequest(
            query=query,
            mode=mode,  # type: ignore[arg-type]
            max_results=max_results,
            freshness_hours=freshness_hours,
        )
        payload = await client.search(request, api_key=exa_api_key)
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
        return items
    finally:
        await client.close()


@tool
async def exa_find_similar(url: str, exa_api_key: str, max_results: int = 5) -> list[dict]:
    """用 Exa 查找与指定 URL 相似的页面。"""
    if not exa_api_key:
        return []

    import httpx
    from app.core.config import get_settings

    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.exa_base_url, timeout=20.0) as client:
        resp = await client.post(
            "/findSimilar",
            json={"url": url, "numResults": min(max_results, 10)},
            headers={"x-api-key": exa_api_key, "content-type": "application/json"},
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
    return items
