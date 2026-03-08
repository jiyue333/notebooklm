from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import httpx

MessageRole = Literal["system", "user", "assistant"]


@dataclass(slots=True)
class ChatMessage:
    role: MessageRole
    content: str


class OpenAILikeClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"

        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def chat_completions(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.__dict__ for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        return response.json()

    async def embeddings(self, *, model: str, input_text: str | list[str]) -> dict[str, Any]:
        response = await self._client.post(
            "/embeddings",
            json={"model": model, "input": input_text},
        )
        response.raise_for_status()
        return response.json()
