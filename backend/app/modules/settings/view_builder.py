from __future__ import annotations

from app.core.config import get_settings as get_system_settings
from app.modules.auth.models import User
from app.modules.settings.defaults import get_default_user_settings
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
    chat_key_state = build_credential_state(
        ciphertext=user.llm_api_key_ciphertext,
        last4=user.llm_api_key_last4,
        default_key=system_settings.llm_default_api_key,
    )
    search_key_state = build_credential_state(
        ciphertext=user.exa_api_key_ciphertext,
        last4=user.exa_api_key_last4,
        default_key=system_settings.exa_default_api_key,
    )
    embedding_key_state = build_credential_state(
        ciphertext=user.embedding_api_key_ciphertext,
        last4=user.embedding_api_key_last4,
        default_key=system_settings.embedding_default_api_key,
    )
    if chat_provider == "ollama" and not chat_key_state["hasCustomKey"]:
        chat_key_state = {**chat_key_state, "hasEffectiveKey": False, "usingDefaultKey": False, "masked": ""}
    if embedding_provider == "ollama" and not embedding_key_state["hasCustomKey"]:
        embedding_key_state = {
            **embedding_key_state,
            "hasEffectiveKey": False,
            "usingDefaultKey": False,
            "masked": "",
        }
    return {
        "outputLanguage": merged["outputLanguage"],
        "themeColor": merged["themeColor"],
        "colorMode": merged["colorMode"],
        "modelProvider": chat_provider,
        "modelName": merged["modelName"],
        "apiUrl": merged["apiUrl"],
        "searchProvider": merged.get("searchProvider", "exa"),
        "usingDefaultModelConfig": not any(field in user_settings for field in {"modelProvider", "modelName", "apiUrl"}),
        "defaultModelProvider": default_settings["modelProvider"],
        "defaultModelName": default_settings["modelName"],
        "defaultApiUrl": default_settings["apiUrl"],
        "embeddingProvider": embedding_provider,
        "embeddingModel": merged["embeddingModel"],
        "embeddingApiUrl": merged["embeddingApiUrl"],
        "usingDefaultSearchConfig": "searchProvider" not in user_settings,
        "defaultSearchProvider": default_settings["searchProvider"],
        "usingDefaultEmbeddingConfig": not any(
            field in user_settings for field in {"embeddingProvider", "embeddingModel", "embeddingApiUrl"}
        ),
        "defaultEmbeddingProvider": default_settings["embeddingProvider"],
        "defaultEmbeddingModel": default_settings["embeddingModel"],
        "defaultEmbeddingApiUrl": default_settings["embeddingApiUrl"],
        "embeddingOutputDimensions": system_settings.embedding_output_dimensions,
        "hasApiKey": chat_key_state["hasEffectiveKey"],
        "hasCustomApiKey": chat_key_state["hasCustomKey"],
        "usingDefaultApiKey": chat_key_state["usingDefaultKey"],
        "apiKeyMasked": chat_key_state["masked"],
        "hasSearchApiKey": search_key_state["hasEffectiveKey"],
        "hasCustomSearchApiKey": search_key_state["hasCustomKey"],
        "usingDefaultSearchApiKey": search_key_state["usingDefaultKey"],
        "searchApiKeyMasked": search_key_state["masked"],
        "hasEmbeddingApiKey": embedding_key_state["hasEffectiveKey"],
        "hasCustomEmbeddingApiKey": embedding_key_state["hasCustomKey"],
        "usingDefaultEmbeddingApiKey": embedding_key_state["usingDefaultKey"],
        "embeddingApiKeyMasked": embedding_key_state["masked"],
        "username": user.name,
    }
