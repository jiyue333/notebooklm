from __future__ import annotations

from app.core.config import get_settings


class Embedder:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.embedding_api_key and self._settings.embedding_api_url)

    async def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        if not texts or not self.is_configured:
            return None

        from langchain_openai import OpenAIEmbeddings

        embeddings = OpenAIEmbeddings(
            model=self._settings.embedding_model,
            dimensions=self._settings.embedding_dimension,
            openai_api_key=self._settings.embedding_api_key,
            openai_api_base=self._settings.embedding_api_url,
        )
        return await embeddings.aembed_documents(texts)
