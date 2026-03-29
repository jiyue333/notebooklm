from __future__ import annotations

from app.core.constant import (
    PROVIDER_EXA,
    PROVIDER_OLLAMA,
)
from app.core.config import get_settings as get_system_settings
from app.modules.auth.models import User
from app.modules.settings.defaults import (
    EMBEDDING_SETTINGS_FIELDS,
    MODEL_SETTINGS_FIELDS,
    SEARCH_SETTINGS_FIELDS,
    get_default_user_settings,
)
from app.modules.settings.runtime import (
    build_credential_state,
    get_merged_user_settings,
    normalize_chat_provider,
    normalize_embedding_provider,
)


def build_settings_view(user: User) -> dict:
    merged = get_merged_user_settings(user)
    user_settings = user.settings_json or {}
    system_settings = get_system_settings()
    default_settings = get_default_user_settings()
    chat_provider = normalize_chat_provider(merged["modelProvider"])
    embedding_provider = normalize_embedding_provider(merged.get("embeddingProvider"))
    miniflux_token_state = build_credential_state(
        ciphertext=user_settings.get("minifluxApiToken"),
        last4=user_settings.get("minifluxApiTokenLast4"),
        default_key=system_settings.miniflux_default_api_token,
    )
    return {
        "outputLanguage": merged["outputLanguage"],
        "themeColor": merged["themeColor"],
        "colorMode": merged["colorMode"],
        "fontFamily": merged.get("fontFamily", "sans"),
        "fontFamilyLatin": merged.get("fontFamilyLatin", "times_new_roman"),
        "fontFamilyCjk": merged.get("fontFamilyCjk", "source_han_serif"),
        "layoutMode": merged.get("layoutMode", "triple"),
        "customSystemPrompt": merged.get("customSystemPrompt", ""),
        "answerLengthPreference": merged.get("answerLengthPreference", "adaptive"),
        "modelProvider": chat_provider,
        "modelName": merged["modelName"],
        "apiUrl": merged["apiUrl"],
        "searchProvider": merged.get("searchProvider", PROVIDER_EXA),
        "preferredSites": merged.get("preferredSites", []),
        "minifluxUrl": merged.get("minifluxUrl", default_settings["minifluxUrl"]),
        "rsshubUrl": merged.get("rsshubUrl", default_settings["rsshubUrl"]),
        "digestTime": merged.get("digestTime", default_settings["digestTime"]),
        "digestLanguage": merged.get("digestLanguage", default_settings["digestLanguage"]),
        "hasMinifluxApiToken": miniflux_token_state["hasEffectiveKey"],
        "hasCustomMinifluxApiToken": miniflux_token_state["hasCustomKey"],
        "usingDefaultMinifluxApiToken": miniflux_token_state["usingDefaultKey"],
        "minifluxApiTokenMasked": miniflux_token_state["masked"],
        "usingDefaultModelConfig": _is_using_default_config(user_settings, MODEL_SETTINGS_FIELDS),
        "defaultModelProvider": normalize_chat_provider(default_settings["modelProvider"]),
        "defaultModelName": default_settings["modelName"],
        "defaultApiUrl": default_settings["apiUrl"],
        "embeddingProvider": embedding_provider,
        "embeddingModel": merged["embeddingModel"],
        "embeddingApiUrl": merged["embeddingApiUrl"],
        "usingDefaultSearchConfig": _is_using_default_config(user_settings, SEARCH_SETTINGS_FIELDS),
        "defaultSearchProvider": default_settings["searchProvider"],
        "usingDefaultEmbeddingConfig": _is_using_default_config(user_settings, EMBEDDING_SETTINGS_FIELDS),
        "defaultEmbeddingProvider": normalize_embedding_provider(default_settings["embeddingProvider"]),
        "defaultEmbeddingModel": default_settings["embeddingModel"],
        "defaultEmbeddingApiUrl": default_settings["embeddingApiUrl"],
        "embeddingOutputDimensions": system_settings.embedding_output_dimensions,
        **_build_chat_api_key_view(user, system_settings, provider=chat_provider),
        **_build_search_api_key_view(user, system_settings),
        **_build_embedding_api_key_view(user, system_settings, provider=embedding_provider),
        "username": user.name,
    }


def _is_using_default_config(user_settings: dict, fields: tuple[str, ...]) -> bool:
    return not any(field in user_settings for field in fields)


def _build_chat_api_key_view(user: User, system_settings, *, provider: str) -> dict:
    return _build_api_key_view(
        ciphertext=user.llm_api_key_ciphertext,
        last4=user.llm_api_key_last4,
        default_key=system_settings.default_chat_api_key,
        provider=provider,
        has_field="hasApiKey",
        custom_field="hasCustomApiKey",
        default_field="usingDefaultApiKey",
        masked_field="apiKeyMasked",
    )


def _build_search_api_key_view(user: User, system_settings) -> dict:
    return _build_api_key_view(
        ciphertext=user.exa_api_key_ciphertext,
        last4=user.exa_api_key_last4,
        default_key=system_settings.exa_default_api_key,
        provider=None,
        has_field="hasSearchApiKey",
        custom_field="hasCustomSearchApiKey",
        default_field="usingDefaultSearchApiKey",
        masked_field="searchApiKeyMasked",
    )


def _build_embedding_api_key_view(user: User, system_settings, *, provider: str) -> dict:
    return _build_api_key_view(
        ciphertext=user.embedding_api_key_ciphertext,
        last4=user.embedding_api_key_last4,
        default_key=system_settings.embedding_default_api_key,
        provider=provider,
        has_field="hasEmbeddingApiKey",
        custom_field="hasCustomEmbeddingApiKey",
        default_field="usingDefaultEmbeddingApiKey",
        masked_field="embeddingApiKeyMasked",
    )


def _build_api_key_view(
    *,
    ciphertext: str | None,
    last4: str | None,
    default_key: str | None,
    provider: str | None,
    has_field: str,
    custom_field: str,
    default_field: str,
    masked_field: str,
) -> dict:
    state = build_credential_state(
        ciphertext=ciphertext,
        last4=last4,
        default_key=default_key,
    )
    if provider == PROVIDER_OLLAMA and not state["hasCustomKey"]:
        state = {**state, "hasEffectiveKey": False, "usingDefaultKey": False, "masked": ""}
    return {
        has_field: state["hasEffectiveKey"],
        custom_field: state["hasCustomKey"],
        default_field: state["usingDefaultKey"],
        masked_field: state["masked"],
    }
