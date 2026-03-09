from __future__ import annotations

DEFAULT_USER_SETTINGS = {
    "outputLanguage": "中文",
    "themeColor": "ocean",
    "colorMode": "light",
    "modelProvider": "openai_compatible",
    "modelName": "gpt-4o",
    "apiUrl": "http://host.docker.internal:8317/v1/chat/completions",
    "searchProvider": "exa",
    "embeddingProvider": "openai_compatible",
    "embeddingModel": "text-embedding-3-large",
    "embeddingApiUrl": "https://api.openai.com/v1",
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
