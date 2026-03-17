from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import SecretStr

from app.core.constant import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_UNKNOWN,
)

if TYPE_CHECKING:
    from langchain_core.embeddings import Embeddings
    from langchain_core.language_models import BaseChatModel


DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_RETRIES = 2


def build_chat_model(
    *,
    provider: str,
    model_name: str,
    base_url: str,
    api_key: str | None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: float | None = None,
    reasoning: bool | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> BaseChatModel:
    """Build a LangChain chat model for the configured provider."""

    shared_metadata = {
        "provider": provider,
        "model_name": model_name,
        **(metadata or {}),
    }
    if provider == PROVIDER_OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model_name,
            base_url=base_url,
            temperature=temperature,
            reasoning=reasoning,
            metadata=shared_metadata,
        )

    if provider == PROVIDER_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model_name": model_name,
            "api_key": SecretStr(api_key) if api_key else None,
            "temperature": temperature,
            "max_retries": max_retries,
            "timeout": timeout,
            "metadata": shared_metadata,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return ChatAnthropic(**kwargs)

    if provider == PROVIDER_GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key) if api_key else None,
            "temperature": temperature,
            "retries": max_retries,
            "request_timeout": timeout,
            "metadata": shared_metadata,
        }
        if base_url:
            kwargs["client_options"] = {"api_endpoint": base_url}
        return ChatGoogleGenerativeAI(**kwargs)

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model_name,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        temperature=temperature,
        max_retries=max_retries,
        timeout=timeout,
        # LangChain docs recommend disabling stream usage metadata when
        # targeting OpenAI-compatible proxies that may not implement it.
        stream_usage=False,
        metadata=shared_metadata,
    )


def build_embeddings_model(
    *,
    provider: str,
    model_name: str,
    base_url: str,
    api_key: str | None,
    output_dimensions: int,
    timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> Embeddings:
    """Build a LangChain embeddings model for the configured provider."""

    if provider == PROVIDER_OLLAMA:
        from langchain_ollama import OllamaEmbeddings

        client_kwargs = {"timeout": timeout} if timeout is not None else {}
        return OllamaEmbeddings(
            model=model_name,
            base_url=base_url,
            async_client_kwargs=client_kwargs,
            sync_client_kwargs=client_kwargs,
        )

    if provider == PROVIDER_GEMINI:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        kwargs = {
            "model": model_name,
            "api_key": SecretStr(api_key) if api_key else None,
            "output_dimensionality": output_dimensions,
        }
        if base_url:
            kwargs["base_url"] = base_url
        return GoogleGenerativeAIEmbeddings(**kwargs)

    if provider == PROVIDER_ANTHROPIC:
        raise ValueError("Anthropic does not provide embeddings")

    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(
        model=model_name,
        api_key=SecretStr(api_key) if api_key else None,
        base_url=base_url,
        dimensions=output_dimensions,
        timeout=timeout,
        max_retries=max_retries,
    )


def get_model_identity(model: Any) -> tuple[str, str]:
    """Return a stable provider/model pair for a LangChain model instance."""

    metadata = getattr(model, "metadata", {}) or {}
    provider = str(metadata.get("provider") or "").strip()
    model_name = str(
        metadata.get("model_name")
        or getattr(model, "model_name", None)
        or getattr(model, "model", None)
        or PROVIDER_UNKNOWN
    ).strip()
    if provider:
        return provider, model_name or PROVIDER_UNKNOWN

    model_type = type(model).__name__.lower()
    if PROVIDER_OLLAMA in model_type:
        return PROVIDER_OLLAMA, model_name or PROVIDER_UNKNOWN
    if PROVIDER_GEMINI.lower() in model_type or "google" in model_type:
        return PROVIDER_GEMINI, model_name or PROVIDER_UNKNOWN
    if "openai" in model_type:
        return PROVIDER_OPENAI, model_name or PROVIDER_UNKNOWN
    return PROVIDER_UNKNOWN, model_name or PROVIDER_UNKNOWN
