from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.api.errors import AppError
from app.modules.ai.prompts.chat_route_prompt import (
    CHAT_ROUTE_SYSTEM_PROMPT,
    CHAT_ROUTE_USER_PROMPT,
)
from app.modules.ai.prompts.chat_prompt import (
    CHAT_ROLLUP_SYSTEM_PROMPT,
    CHAT_ROLLUP_USER_PROMPT,
    CHAT_SYSTEM_PROMPT,
    CHAT_USER_PROMPT,
)
from app.modules.ai.prompts.summary_prompt import SUMMARY_SYSTEM_PROMPT, SUMMARY_USER_PROMPT
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


def build_summary_chain(user):
    return build_summary_prompt() | require_user_chat_model(user) | StrOutputParser()


def build_chat_chain(user):
    return build_chat_prompt() | require_user_chat_model(user) | StrOutputParser()


def build_chat_rollup_chain(user):
    return build_chat_rollup_prompt() | require_user_chat_model(user) | StrOutputParser()


def build_chat_router_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_ROUTE_SYSTEM_PROMPT),
            ("human", CHAT_ROUTE_USER_PROMPT),
        ]
    )


def build_summary_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_SYSTEM_PROMPT),
            ("human", SUMMARY_USER_PROMPT),
        ]
    )


def build_chat_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_SYSTEM_PROMPT),
            MessagesPlaceholder("history_messages"),
            ("human", CHAT_USER_PROMPT),
        ]
    )


def build_chat_rollup_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_ROLLUP_SYSTEM_PROMPT),
            ("human", CHAT_ROLLUP_USER_PROMPT),
        ]
    )
