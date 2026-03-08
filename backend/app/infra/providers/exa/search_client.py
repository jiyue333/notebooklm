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

        payload = {
            "query": request.query,
            "type": request.mode,
            "numResults": request.max_results,
            "contents": {
                "highlights": {
                    "query": request.query,
                    "highlightsPerUrl": 3,
                    "numSentences": 3,
                }
            },
        }
        # Exa freshness knobs are intentionally kept in the adapter so later
        # steps can tune them without leaking provider details upward.
        if request.freshness_hours is not None:
            payload["maxAgeHours"] = request.freshness_hours

        response = await self._client.post(
            "/search",
            json=payload,
            headers={"x-api-key": api_key},
        )
        response.raise_for_status()
        return response.json()
