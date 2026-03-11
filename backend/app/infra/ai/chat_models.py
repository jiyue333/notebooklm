from __future__ import annotations

from app.api.errors import AppError
from app.modules.settings.runtime import resolve_chat_runtime_config


def get_user_generation_settings(user) -> dict:
    runtime_config = resolve_chat_runtime_config(user)
    return {
        "modelProvider": runtime_config.provider,
        "modelName": runtime_config.model_name,
        "apiUrl": runtime_config.api_url,
        "outputLanguage": runtime_config.output_language,
        "keySource": runtime_config.key_source,
    }


def build_user_chat_model(user):
    runtime_config = resolve_chat_runtime_config(user)
    if not runtime_config.is_configured:
        return None
    if runtime_config.provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=runtime_config.model_name,
            base_url=runtime_config.api_url,
            temperature=0.0,
            reasoning=False,
        )

    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    api_key_secret = SecretStr(runtime_config.api_key) if runtime_config.api_key else None
    return ChatOpenAI(
        model=runtime_config.model_name,
        api_key=api_key_secret,
        base_url=runtime_config.api_url,
        temperature=0.0,
        max_retries=2,
    )


def require_user_chat_model(user):
    model = build_user_chat_model(user)
    if model is None:
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")
    return model
