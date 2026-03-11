from __future__ import annotations

from datetime import datetime

from app.modules.settings.defaults import SETTINGS_FIELDS

MODEL_SETTINGS_FIELDS = ("modelProvider", "modelName", "apiUrl")
SEARCH_SETTINGS_FIELDS = ("searchProvider",)
EMBEDDING_SETTINGS_FIELDS = ("embeddingProvider", "embeddingModel", "embeddingApiUrl")


def merge_settings_payload(
    *,
    stored_settings: dict,
    payload: dict,
    default_settings: dict,
) -> tuple[dict, dict]:
    settings_json = {**stored_settings}
    use_default_model_config = bool(payload.get("useDefaultModelConfig"))
    use_default_search_config = bool(payload.get("useDefaultSearchConfig"))
    use_default_embedding_config = bool(payload.get("useDefaultEmbeddingConfig"))

    for field in SETTINGS_FIELDS:
        if use_default_model_config and field in MODEL_SETTINGS_FIELDS:
            continue
        if use_default_search_config and field in SEARCH_SETTINGS_FIELDS:
            continue
        if use_default_embedding_config and field in EMBEDDING_SETTINGS_FIELDS:
            continue
        if field in payload and payload[field] is not None:
            settings_json[field] = payload[field]

    if use_default_model_config:
        drop_settings_fields(settings_json, MODEL_SETTINGS_FIELDS)
    if use_default_search_config:
        drop_settings_fields(settings_json, SEARCH_SETTINGS_FIELDS)
    if use_default_embedding_config:
        drop_settings_fields(settings_json, EMBEDDING_SETTINGS_FIELDS)

    return settings_json, {**default_settings, **settings_json}


def drop_settings_fields(settings_json: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        settings_json.pop(field, None)


def apply_credential_updates(*, user, payload: dict, crypto, now: datetime) -> None:
    if payload.get("useDefaultModelConfig") or payload.get("clearApiKey"):
        user.llm_api_key_ciphertext = None
        user.llm_api_key_last4 = None
        user.llm_api_key_updated_at = now
    elif payload.get("apiKey"):
        api_key = payload["apiKey"].strip()
        user.llm_api_key_ciphertext = crypto.encrypt(api_key)
        user.llm_api_key_last4 = api_key[-4:]
        user.llm_api_key_updated_at = now

    if payload.get("useDefaultSearchConfig") or payload.get("clearSearchApiKey"):
        user.exa_api_key_ciphertext = None
        user.exa_api_key_last4 = None
        user.exa_api_key_updated_at = now
    elif payload.get("searchApiKey"):
        search_api_key = payload["searchApiKey"].strip()
        user.exa_api_key_ciphertext = crypto.encrypt(search_api_key)
        user.exa_api_key_last4 = search_api_key[-4:]
        user.exa_api_key_updated_at = now

    if payload.get("useDefaultEmbeddingConfig") or payload.get("clearEmbeddingApiKey"):
        user.embedding_api_key_ciphertext = None
        user.embedding_api_key_last4 = None
        user.embedding_api_key_updated_at = now
    elif payload.get("embeddingApiKey"):
        embedding_api_key = payload["embeddingApiKey"].strip()
        user.embedding_api_key_ciphertext = crypto.encrypt(embedding_api_key)
        user.embedding_api_key_last4 = embedding_api_key[-4:]
        user.embedding_api_key_updated_at = now
