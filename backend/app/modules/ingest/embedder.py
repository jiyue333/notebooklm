from __future__ import annotations

from app.modules.settings.runtime import EmbeddingRuntimeConfig, resolve_embedding_runtime_config


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
            from langchain_ollama import OllamaEmbeddings

            embeddings = OllamaEmbeddings(
                model=self._runtime_config.model_name,
                base_url=self._runtime_config.api_url,
            )
            return await embeddings.aembed_documents(texts)

        from langchain_openai import OpenAIEmbeddings
        from pydantic import SecretStr

        api_key_secret = SecretStr(self._runtime_config.api_key) if self._runtime_config.api_key else None

        embeddings = OpenAIEmbeddings(
            model=self._runtime_config.model_name,
            api_key=api_key_secret,
            base_url=self._runtime_config.api_url,
        )
        return await embeddings.aembed_documents(texts)
