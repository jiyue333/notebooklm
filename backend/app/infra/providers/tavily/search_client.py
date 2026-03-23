from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class TavilySearchRequest:
    query: str
    search_depth: str = "advanced"
    max_results: int = 8
    topic: str = "general"
    time_range: str | None = None
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    chunks_per_source: int = 3
    include_raw_content: bool | str = False


class TavilySearchClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._settings.tavily_base_url,
            timeout=30.0,
            headers={"content-type": "application/json"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, request: TavilySearchRequest, *, api_key: str) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Tavily api key is required")

        payload: dict[str, Any] = {
            "api_key": api_key,
            "query": request.query,
            "search_depth": request.search_depth,
            "topic": request.topic,
            "max_results": max(1, min(request.max_results, 20)),
            "chunks_per_source": max(1, min(request.chunks_per_source, 5)),
            "include_raw_content": request.include_raw_content,
        }
        if request.time_range:
            payload["time_range"] = request.time_range
        if request.include_domains:
            payload["include_domains"] = request.include_domains
        if request.exclude_domains:
            payload["exclude_domains"] = request.exclude_domains
        if request.exclude_paths:
            payload["exclude_paths"] = request.exclude_paths

        response = await self._client.post("/search", json=payload)
        response.raise_for_status()
        return response.json()
