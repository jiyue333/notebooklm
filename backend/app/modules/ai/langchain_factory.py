from __future__ import annotations

from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS


def build_user_chat_model(user):
    if not user.llm_api_key_ciphertext:
        return None

    from langchain_openai import ChatOpenAI

    settings_json = {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})}
    api_key = get_credential_crypto().decrypt(user.llm_api_key_ciphertext)
    return ChatOpenAI(
        model_name=settings_json["modelName"],
        openai_api_key=api_key,
        openai_api_base=settings_json["apiUrl"],
        temperature=0.0,
        max_retries=2,
    )
