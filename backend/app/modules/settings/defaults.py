from __future__ import annotations

from app.core.config import get_settings


def get_default_user_settings() -> dict:
    settings = get_settings()
    return {
        "outputLanguage": "中文",
        "themeColor": "ocean",
        "colorMode": "light",
        "modelProvider": settings.default_chat_provider,
        "modelName": settings.default_chat_model_name,
        "apiUrl": settings.default_chat_api_url,
        "searchProvider": settings.default_search_provider,
        "embeddingProvider": settings.default_embedding_provider,
        "embeddingModel": settings.default_embedding_model_name,
        "embeddingApiUrl": settings.default_embedding_api_url,
    }


SETTINGS_FIELDS = {
    "outputLanguage",
    "themeColor",
    "colorMode",
    "modelProvider",
    "modelName",
    "apiUrl",
    "searchProvider",
    "embeddingProvider",
    "embeddingModel",
    "embeddingApiUrl",
}
