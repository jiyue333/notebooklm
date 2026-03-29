from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlparse

import structlog
from cryptography.fernet import InvalidToken

from app.core.config import Settings, get_settings
from app.core.constant import (
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
)
from app.infra.security.credential_crypto import get_credential_crypto
from app.modules.settings.defaults import get_default_user_settings

logger = structlog.get_logger(__name__)
_PREFERRED_SITE_MAX_COUNT = 8
_PREFERRED_SITE_MAX_LENGTH = 120
_DOMAIN_PATTERN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


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
        if self.provider == PROVIDER_OLLAMA:
            return bool(self.model_name and self.api_url)
        if self.provider in {PROVIDER_ANTHROPIC, PROVIDER_GEMINI}:
            return bool(self.model_name and self.api_key)
        return bool(self.model_name and self.api_url and self.api_key)


@dataclass(slots=True)
class EmbeddingRuntimeConfig:
    provider: str
    model_name: str
    api_url: str
    api_key: str | None
    output_dimensions: int
    key_source: str

    @property
    def is_configured(self) -> bool:
        if self.provider == PROVIDER_OLLAMA:
            return bool(self.model_name and self.api_url)
        if self.provider == PROVIDER_GEMINI:
            return bool(self.model_name and self.api_key)
        if self.provider == PROVIDER_ANTHROPIC:
            return False
        return bool(self.model_name and self.api_url and self.api_key)

    @property
    def profile_key(self) -> str:
        raw = f"{self.provider}|{self.model_name}|{self.api_url.rstrip('/')}|{self.output_dimensions}"
        return sha256(raw.encode("utf-8")).hexdigest()


def get_merged_user_settings(user) -> dict:
    user_overrides = (getattr(user, "settings_json", None) or {}) if user else {}
    return {**get_default_user_settings(), **user_overrides}


def resolve_preferred_sites(user) -> list[str]:
    merged = get_merged_user_settings(user)
    raw_sites = merged.get("preferredSites") or []
    sites: list[str] = []
    for site in raw_sites:
        normalized = str(site).strip().lower()
        if not normalized:
            continue
        normalized = normalized.removeprefix("*.")
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        domain = parsed.netloc.strip().lower() or parsed.path.strip().lower()
        domain = domain.split("/")[0].split("?")[0].split("#")[0]
        if ":" in domain:
            domain = domain.split(":", 1)[0]
        if not domain:
            continue
        if len(domain) > _PREFERRED_SITE_MAX_LENGTH:
            continue
        if not _DOMAIN_PATTERN.match(domain):
            continue
        sites.append(domain)
        if len(sites) >= _PREFERRED_SITE_MAX_COUNT:
            break
    return list(dict.fromkeys(sites))


def normalize_chat_provider(value: str | None) -> str:
    normalized = (value or "").strip()
    lowered = normalized.lower()
    if lowered == PROVIDER_OLLAMA.lower():
        return PROVIDER_OLLAMA
    if lowered in {PROVIDER_ANTHROPIC.lower(), "claude"}:
        return PROVIDER_ANTHROPIC
    if lowered in {PROVIDER_GEMINI.lower(), "google", "google-genai", "google_genai"}:
        return PROVIDER_GEMINI
    if lowered in {PROVIDER_OPENAI.lower(), "openai_compatible", "openai-compatible", "custom", "自定义"}:
        return PROVIDER_OPENAI
    return PROVIDER_OPENAI


def normalize_embedding_provider(value: str | None) -> str:
    normalized = (value or "").strip()
    lowered = normalized.lower()
    if lowered == PROVIDER_OLLAMA.lower():
        return PROVIDER_OLLAMA
    if lowered == PROVIDER_ANTHROPIC.lower():
        return PROVIDER_ANTHROPIC
    if lowered in {PROVIDER_GEMINI.lower(), "google", "google-genai", "google_genai"}:
        return PROVIDER_GEMINI
    if lowered in {PROVIDER_OPENAI.lower(), "openai_compatible", "openai-compatible", "custom", "自定义"}:
        return PROVIDER_OPENAI
    return PROVIDER_OPENAI


def resolve_search_api_key(user, settings: Settings | None = None) -> tuple[str | None, str]:
    runtime_settings = settings or get_settings()
    if user.exa_api_key_ciphertext:
        decrypted = _decrypt_user_key(
            user.exa_api_key_ciphertext,
            credential_name="search_api_key",
        )
        if decrypted:
            return decrypted, "user"
    if runtime_settings.exa_default_api_key:
        return runtime_settings.exa_default_api_key, "default"
    return None, "missing"


def resolve_tavily_api_key(
    user=None,
    settings: Settings | None = None,
) -> tuple[str | None, str]:
    runtime_settings = settings or get_settings()
    if user is not None:
        ciphertext = getattr(user, "tavily_api_key_ciphertext", None)
        if ciphertext:
            decrypted = _decrypt_user_key(
                ciphertext,
                credential_name="tavily_api_key",
            )
            if decrypted:
                return decrypted, "user"
        user_settings = get_merged_user_settings(user)
        plain = str(user_settings.get("tavilyApiKey") or "").strip()
        if plain:
            return plain, "user"
    if runtime_settings.tavily_default_api_key:
        return runtime_settings.tavily_default_api_key, "default"
    return None, "missing"


def resolve_chat_runtime_config(user, settings: Settings | None = None) -> ChatRuntimeConfig:
    runtime_settings = settings or get_settings()
    merged = get_merged_user_settings(user)
    provider, model_name, api_url = _resolve_provider_model_api(
        merged=merged,
        provider_field="modelProvider",
        model_field="modelName",
        api_url_field="apiUrl",
        normalize_provider=normalize_chat_provider,
    )
    api_key, key_source = _resolve_provider_api_key(
        provider=provider,
        ciphertext=user.llm_api_key_ciphertext,
        default_key=runtime_settings.default_chat_api_key,
    )
    return ChatRuntimeConfig(
        provider=provider,
        model_name=model_name,
        api_url=api_url,
        api_key=api_key,
        output_language=_resolve_defaulted_string(merged=merged, field="outputLanguage"),
        key_source=key_source,
    )


def resolve_embedding_runtime_config(user, settings: Settings | None = None) -> EmbeddingRuntimeConfig:
    runtime_settings = settings or get_settings()
    merged = get_merged_user_settings(user)
    return resolve_embedding_runtime_config_from_merged(
        merged=merged,
        user=user,
        settings=runtime_settings,
    )


def resolve_embedding_profile_key_from_merged(
    *,
    merged: dict,
    settings: Settings | None = None,
) -> str:
    runtime_settings = settings or get_settings()
    provider, model_name, api_url = _resolve_provider_model_api(
        merged=merged,
        provider_field="embeddingProvider",
        model_field="embeddingModel",
        api_url_field="embeddingApiUrl",
        normalize_provider=normalize_embedding_provider,
    )
    raw = f"{provider}|{model_name}|{api_url.rstrip('/')}|{runtime_settings.embedding_output_dimensions}"
    return sha256(raw.encode("utf-8")).hexdigest()


def resolve_embedding_runtime_config_from_merged(
    *,
    merged: dict,
    user,
    settings: Settings | None = None,
) -> EmbeddingRuntimeConfig:
    runtime_settings = settings or get_settings()
    provider, model_name, api_url = _resolve_provider_model_api(
        merged=merged,
        provider_field="embeddingProvider",
        model_field="embeddingModel",
        api_url_field="embeddingApiUrl",
        normalize_provider=normalize_embedding_provider,
    )
    api_key, key_source = _resolve_provider_api_key(
        provider=provider,
        ciphertext=getattr(user, "embedding_api_key_ciphertext", None),
        default_key=runtime_settings.embedding_default_api_key,
    )
    return EmbeddingRuntimeConfig(
        provider=provider,
        model_name=model_name,
        api_url=api_url,
        api_key=api_key,
        output_dimensions=runtime_settings.embedding_output_dimensions,
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
    masked = _mask_last4(last4)
    if not masked and using_default and default_key:
        masked = _mask_last4(default_key[-4:])
    return {
        "hasEffectiveKey": has_custom or using_default,
        "hasCustomKey": has_custom,
        "usingDefaultKey": using_default,
        "masked": masked,
    }


def _mask_last4(last4: str | None) -> str:
    return f"••••{last4}" if last4 else ""


def _resolve_key(*, ciphertext: str | None, default_key: str | None) -> tuple[str | None, str]:
    if ciphertext:
        decrypted = _decrypt_user_key(
            ciphertext,
            credential_name="user_api_key",
        )
        if decrypted:
            return decrypted, "user"
    if default_key:
        return default_key, "default"
    return None, "missing"


def _decrypt_user_key(ciphertext: str, *, credential_name: str) -> str | None:
    try:
        return get_credential_crypto().decrypt(ciphertext)
    except InvalidToken:
        logger.warning(
            "settings.invalid_encrypted_credential",
            credential_name=credential_name,
        )
        return None


def _resolve_provider_api_key(
    *,
    provider: str,
    ciphertext: str | None,
    default_key: str | None,
) -> tuple[str | None, str]:
    if provider == PROVIDER_OLLAMA:
        return None, "not_required"
    return _resolve_key(ciphertext=ciphertext, default_key=default_key)


def _resolve_provider_model_api(
    *,
    merged: dict,
    provider_field: str,
    model_field: str,
    api_url_field: str,
    normalize_provider,
) -> tuple[str, str, str]:
    provider = normalize_provider(merged.get(provider_field))
    return (
        provider,
        _resolve_defaulted_string(merged=merged, field=model_field),
        _resolve_api_base(merged=merged, field=api_url_field),
    )


def _resolve_defaulted_string(*, merged: dict, field: str) -> str:
    defaults = get_default_user_settings()
    return str(merged.get(field) or defaults[field]).strip()


def _resolve_api_base(*, merged: dict, field: str) -> str:
    defaults = get_default_user_settings()
    if field in merged and merged[field] is not None:
        return _normalize_api_base(str(merged[field]).strip())
    return _normalize_api_base(str(defaults[field]).strip())


def _normalize_api_base(api_url: str) -> str:
    value = api_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value
