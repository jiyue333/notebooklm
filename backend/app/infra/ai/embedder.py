from __future__ import annotations

import asyncio

import httpx

from app.modules.settings.runtime import EmbeddingRuntimeConfig, resolve_embedding_runtime_config

_EMBED_TIMEOUT_SECONDS = 120


class Embedder:
    def __init__(self, runtime_config: EmbeddingRuntimeConfig) -> None:
        self._runtime_config = runtime_config

    @classmethod
    def from_user(cls, user):
        return cls(resolve_embedding_runtime_config(user))

    @property
    def is_configured(self) -> bool:
        return self._runtime_config.is_configured

    @property
    def provider(self) -> str:
        return self._runtime_config.provider

    @property
    def model_name(self) -> str:
        return self._runtime_config.model_name

    @property
    def profile_key(self) -> str:
        return self._runtime_config.profile_key

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not texts or not self.is_configured:
            return None

        if self._runtime_config.provider == "ollama":
            timeout = httpx.Timeout(180.0, connect=10.0)
            async with httpx.AsyncClient(
                base_url=self._runtime_config.api_url,
                timeout=timeout,
                trust_env=False,
            ) as client:
                response = await client.post(
                    "/api/embed",
                    json={
                        "model": self._runtime_config.model_name,
                        "input": texts,
                        "dimensions": self._runtime_config.output_dimensions,
                    },
                )
                response.raise_for_status()
                payload = response.json()
            embeddings = payload.get("embeddings") or []
            return _validate_embedding_dimensions(
                embeddings,
                expected_dimensions=self._runtime_config.output_dimensions,
            )

        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        api_key_secret = SecretStr(self._runtime_config.api_key) if self._runtime_config.api_key else None
        embeddings = OpenAIEmbeddings(
            model=self._runtime_config.model_name,
            api_key=api_key_secret,
            base_url=self._runtime_config.api_url,
            request_timeout=_EMBED_TIMEOUT_SECONDS,
        )
        response = await asyncio.wait_for(
            embeddings.aembed_documents(texts),
            timeout=_EMBED_TIMEOUT_SECONDS,
        )
        return _validate_embedding_dimensions(
            response,
            expected_dimensions=self._runtime_config.output_dimensions,
        )


def _validate_embedding_dimensions(
    embeddings: list[list[float]],
    *,
    expected_dimensions: int,
) -> list[list[float]]:
    if embeddings and len(embeddings[0]) != expected_dimensions:
        raise RuntimeError(
            f"embedding dimension mismatch: expected {expected_dimensions}, got {len(embeddings[0])}"
        )
    return embeddings
