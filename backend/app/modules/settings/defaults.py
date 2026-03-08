from __future__ import annotations

DEFAULT_USER_SETTINGS = {
    "outputLanguage": "中文",
    "themeColor": "ocean",
    "colorMode": "light",
    "modelProvider": "自定义",
    "modelName": "gpt-4o",
    "apiUrl": "http://host.docker.internal:8317/v1/chat/completions",
    "searchProvider": "exa",
}

SETTINGS_FIELDS = {
    "outputLanguage",
    "themeColor",
    "colorMode",
    "modelProvider",
    "modelName",
    "apiUrl",
    "searchProvider",
}
