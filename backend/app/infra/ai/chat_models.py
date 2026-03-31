from __future__ import annotations

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.ai.factory import build_chat_model
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
    settings = get_settings()
    runtime_config = resolve_chat_runtime_config(user, settings)
    if not runtime_config.is_configured:
        return None
    return build_chat_model(
        provider=runtime_config.provider,
        model_name=runtime_config.model_name,
        base_url=runtime_config.api_url,
        api_key=runtime_config.api_key,
        timeout=float(settings.chat_model_timeout),
        max_output_tokens=settings.chat_max_tokens,
        metadata={"key_source": runtime_config.key_source},
    )


def require_user_chat_model(user):
    model = build_user_chat_model(user)
    if model is None:
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")
    return model
