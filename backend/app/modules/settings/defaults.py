from __future__ import annotations

from app.core.config import get_settings

MODEL_SETTINGS_FIELDS = ("modelProvider", "modelName", "apiUrl")
SEARCH_SETTINGS_FIELDS = ("searchProvider", "preferredSites")
EMBEDDING_SETTINGS_FIELDS = ("embeddingProvider", "embeddingModel", "embeddingApiUrl")
SETTINGS_SCOPE_FIELDS = {
    "model": MODEL_SETTINGS_FIELDS,
    "search": SEARCH_SETTINGS_FIELDS,
    "embedding": EMBEDDING_SETTINGS_FIELDS,
}
SETTINGS_FIELDS = (
    "outputLanguage",
    "themeColor",
    "colorMode",
    "customSystemPrompt",
    "answerLengthPreference",
    *MODEL_SETTINGS_FIELDS,
    *SEARCH_SETTINGS_FIELDS,
    *EMBEDDING_SETTINGS_FIELDS,
)


def get_default_user_settings() -> dict:
    settings = get_settings()
    return {
        "outputLanguage": "中文",
        "themeColor": "ocean",
        "colorMode": "light",
        "customSystemPrompt": "",
        "answerLengthPreference": "adaptive",
        "modelProvider": settings.default_chat_provider,
        "modelName": settings.default_chat_model_name,
        "apiUrl": settings.default_chat_api_url,
        "searchProvider": settings.default_search_provider,
        "preferredSites": [],
        "embeddingProvider": settings.default_embedding_provider,
        "embeddingModel": settings.default_embedding_model_name,
        "embeddingApiUrl": settings.default_embedding_api_url,
    }
