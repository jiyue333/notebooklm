from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import Settings, get_settings

LivecrawlMode = Literal["fallback", "preferred"]


@dataclass(slots=True)
class ExaContentsRequest:
    urls: list[str]
    include_text: bool = True
    include_summary: bool = False
    include_highlights: bool = False
    livecrawl: LivecrawlMode = "fallback"
    max_characters: int | None = None


class ExaContentsClient:
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
            timeout=60.0,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch(self, request: ExaContentsRequest, *, api_key: str) -> dict[str, Any]:
        if not api_key:
            raise ValueError("Exa api key is required")

        payload: dict[str, Any] = {
            "urls": request.urls,
            "livecrawl": request.livecrawl,
            "text": request.include_text,
            "summary": request.include_summary,
            "highlights": request.include_highlights,
        }
        if request.max_characters is not None:
            payload["maxCharacters"] = request.max_characters

        response = await self._client.post(
            "/contents",
            json=payload,
            headers={"x-api-key": api_key},
        )
        response.raise_for_status()
        return response.json()
