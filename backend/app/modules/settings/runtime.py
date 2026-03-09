from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.core.config import Settings, get_settings
from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS

OPENAI_COMPATIBLE_PROVIDERS = {
    "",
    "openai_compatible",
    "openai-compatible",
    "openai",
    "custom",
    "自定义",
    "anthropic",
    "google",
}
OLLAMA_PROVIDERS = {"ollama"}


@dataclass(slots=True)
class ChatRuntimeConfig:
    provider: str
    model_name: str
    api_url: str
    api_key: str | None
    output_language: str
    key_source: str

    @property
    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.model_name and self.api_url)
        return bool(self.model_name and self.api_url and self.api_key)


@dataclass(slots=True)
class EmbeddingRuntimeConfig:
    provider: str
    model_name: str
    api_url: str
    api_key: str | None
    key_source: str

    @property
    def is_configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.model_name and self.api_url)
        return bool(self.model_name and self.api_url and self.api_key)

    @property
    def profile_key(self) -> str:
        raw = f"{self.provider}|{self.model_name}|{self.api_url.rstrip('/')}"
        return sha256(raw.encode("utf-8")).hexdigest()


def get_merged_user_settings(user) -> dict:
    return {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})}


def normalize_chat_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in OLLAMA_PROVIDERS:
        return "ollama"
    return "openai_compatible"


def normalize_embedding_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in OLLAMA_PROVIDERS:
        return "ollama"
    if normalized in OPENAI_COMPATIBLE_PROVIDERS:
        return "openai_compatible"
    return "openai_compatible"


def resolve_search_api_key(user, settings: Settings | None = None) -> tuple[str | None, str]:
    runtime_settings = settings or get_settings()
    if user.exa_api_key_ciphertext:
        return get_credential_crypto().decrypt(user.exa_api_key_ciphertext), "user"
    if runtime_settings.exa_default_api_key:
        return runtime_settings.exa_default_api_key, "default"
    return None, "missing"


def resolve_chat_runtime_config(user, settings: Settings | None = None) -> ChatRuntimeConfig:
    runtime_settings = settings or get_settings()
    merged = get_merged_user_settings(user)
    provider = normalize_chat_provider(merged.get("modelProvider"))
    api_key, key_source = _resolve_key(
        ciphertext=user.llm_api_key_ciphertext,
        default_key=runtime_settings.llm_default_api_key,
    )
    return ChatRuntimeConfig(
        provider=provider,
        model_name=str(merged.get("modelName") or DEFAULT_USER_SETTINGS["modelName"]).strip(),
        api_url=_normalize_api_base(str(merged.get("apiUrl") or DEFAULT_USER_SETTINGS["apiUrl"])),
        api_key=api_key,
        output_language=str(merged.get("outputLanguage") or DEFAULT_USER_SETTINGS["outputLanguage"]),
        key_source=key_source,
    )


def resolve_embedding_runtime_config(user, settings: Settings | None = None) -> EmbeddingRuntimeConfig:
    runtime_settings = settings or get_settings()
    merged = get_merged_user_settings(user)
    provider = normalize_embedding_provider(merged.get("embeddingProvider"))
    api_key, key_source = _resolve_key(
        ciphertext=user.embedding_api_key_ciphertext,
        default_key=runtime_settings.embedding_default_api_key,
    )
    return EmbeddingRuntimeConfig(
        provider=provider,
        model_name=str(merged.get("embeddingModel") or DEFAULT_USER_SETTINGS["embeddingModel"]).strip(),
        api_url=_normalize_api_base(str(merged.get("embeddingApiUrl") or DEFAULT_USER_SETTINGS["embeddingApiUrl"])),
        api_key=api_key,
        key_source=key_source,
    )


def build_credential_state(
    *,
    ciphertext: str | None,
    last4: str | None,
    default_key: str | None,
) -> dict:
    has_custom = bool(ciphertext)
    using_default = bool(default_key) and not has_custom
    return {
        "hasEffectiveKey": has_custom or using_default,
        "hasCustomKey": has_custom,
        "usingDefaultKey": using_default,
        "masked": _mask_last4(last4),
    }


def _mask_last4(last4: str | None) -> str:
    return f"••••{last4}" if last4 else ""


def _resolve_key(*, ciphertext: str | None, default_key: str | None) -> tuple[str | None, str]:
    if ciphertext:
        return get_credential_crypto().decrypt(ciphertext), "user"
    if default_key:
        return default_key, "default"
    return None, "missing"


def _normalize_api_base(api_url: str) -> str:
    value = api_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value
