from __future__ import annotations

import asyncio

from app.infra.ai.factory import build_embeddings_model
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

        embeddings = build_embeddings_model(
            provider=self._runtime_config.provider,
            model_name=self._runtime_config.model_name,
            base_url=self._runtime_config.api_url,
            api_key=self._runtime_config.api_key,
            output_dimensions=self._runtime_config.output_dimensions,
            timeout=_EMBED_TIMEOUT_SECONDS,
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
