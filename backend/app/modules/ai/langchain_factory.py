from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.api.errors import AppError
from app.modules.ai.prompts.chat_prompt import (
    CHAT_ROLLUP_SYSTEM_PROMPT,
    CHAT_ROLLUP_USER_PROMPT,
    CHAT_SYSTEM_PROMPT,
    CHAT_USER_PROMPT,
)
from app.modules.ai.prompts.summary_prompt import SUMMARY_SYSTEM_PROMPT, SUMMARY_USER_PROMPT
from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS


def get_user_generation_settings(user) -> dict:
    settings_json = {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})}
    return {
        "modelProvider": settings_json["modelProvider"],
        "modelName": settings_json["modelName"],
        "apiUrl": _normalize_api_base(settings_json["apiUrl"]),
        "outputLanguage": settings_json["outputLanguage"],
    }


def build_user_chat_model(user):
    if not user.llm_api_key_ciphertext:
        return None

    from langchain_openai import ChatOpenAI

    settings_json = get_user_generation_settings(user)
    api_key = get_credential_crypto().decrypt(user.llm_api_key_ciphertext)
    return ChatOpenAI(
        model=settings_json["modelName"],
        api_key=api_key,
        base_url=settings_json["apiUrl"],
        temperature=0.0,
        max_retries=2,
    )


def require_user_chat_model(user):
    model = build_user_chat_model(user)
    if model is None:
        raise AppError(422, "请先在设置中配置模型 API Key", code="model_config_required")
    return model


def build_summary_chain(user):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_SYSTEM_PROMPT),
            ("human", SUMMARY_USER_PROMPT),
        ]
    )
    return prompt | require_user_chat_model(user) | StrOutputParser()


def build_chat_chain(user):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_SYSTEM_PROMPT),
            MessagesPlaceholder("history_messages"),
            ("human", CHAT_USER_PROMPT),
        ]
    )
    return prompt | require_user_chat_model(user) | StrOutputParser()


def build_chat_rollup_chain(user):
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_ROLLUP_SYSTEM_PROMPT),
            ("human", CHAT_ROLLUP_USER_PROMPT),
        ]
    )
    return prompt | require_user_chat_model(user) | StrOutputParser()


def _normalize_api_base(api_url: str) -> str:
    value = api_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value
