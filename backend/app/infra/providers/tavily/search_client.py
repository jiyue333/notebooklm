from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tavily import AsyncTavilyClient

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
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def close(self) -> None:
        # 兼容旧用法（原先持有 httpx 连接池）；SDK 按请求创建客户端时无需释放
        pass

    async def search(self, request: TavilySearchRequest, *, api_key: str) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Tavily api key is required")

        kwargs: dict[str, Any] = {
            "search_depth": request.search_depth,
            "topic": request.topic,
            "max_results": max(1, min(request.max_results, 20)),
            "include_raw_content": request.include_raw_content,
            "chunks_per_source": max(1, min(request.chunks_per_source, 5)),
            "timeout": 30.0,
        }
        if request.time_range:
            kwargs["time_range"] = request.time_range
        if request.include_domains:
            kwargs["include_domains"] = request.include_domains
        if request.exclude_domains:
            kwargs["exclude_domains"] = request.exclude_domains
        if request.exclude_paths:
            kwargs["exclude_paths"] = request.exclude_paths

        client = AsyncTavilyClient(
            api_key=api_key,
            api_base_url=self._settings.tavily_base_url,
        )
        try:
            return await client.search(request.query, **kwargs)
        finally:
            await client.close()
