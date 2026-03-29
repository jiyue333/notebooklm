from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import Settings, get_settings

ExaSearchMode = Literal["fast", "auto", "deep"]


@dataclass(slots=True)
class ExaSearchRequest:
    query: str
    mode: ExaSearchMode = "auto"
    max_results: int = 10
    freshness_hours: int | None = None
    include_domains: list[str] | None = None
    exclude_domains: list[str] | None = None
    timeout_seconds: float | None = None


class ExaSearchClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._settings.exa_base_url,
            headers={"content-type": "application/json"},
            timeout=30.0,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search(self, request: ExaSearchRequest, *, api_key: str) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Exa api key is required")

        contents: dict[str, Any] = {
            "highlights": {
                "query": request.query,
                "maxCharacters": 1800,
            },
            "livecrawlTimeout": 10000,
        }
        if request.freshness_hours is not None:
            contents["maxAgeHours"] = request.freshness_hours

        payload = {
            "query": request.query,
            "type": request.mode,
            "numResults": request.max_results,
            "contents": contents,
        }
        if request.include_domains:
            payload["includeDomains"] = request.include_domains
        if request.exclude_domains:
            payload["excludeDomains"] = request.exclude_domains

        response = await self._client.post(
            "/search",
            json=payload,
            headers={"x-api-key": api_key},
            timeout=request.timeout_seconds or self._client.timeout,
        )
        response.raise_for_status()
        return response.json()
