from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.settings.runtime import (
    resolve_chat_runtime_config,
    resolve_embedding_runtime_config,
)
from app.modules.settings.service import update_settings


def make_user(**overrides):
    defaults = {
        "id": "user-1",
        "name": "tester",
        "settings_json": {},
        "llm_api_key_ciphertext": None,
        "llm_api_key_last4": None,
        "llm_api_key_updated_at": None,
        "exa_api_key_ciphertext": None,
        "exa_api_key_last4": None,
        "exa_api_key_updated_at": None,
        "embedding_api_key_ciphertext": None,
        "embedding_api_key_last4": None,
        "embedding_api_key_updated_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class DummySession:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshed = None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, user) -> None:
        self.refreshed = user


def test_chat_runtime_ignores_user_key_for_ollama() -> None:
    user = make_user(
        settings_json={
            "modelProvider": "ollama",
            "modelName": "qwen3.5:0.8b",
            "apiUrl": "http://127.0.0.1:11434",
        },
        llm_api_key_ciphertext="not-a-valid-fernet-token",
    )

    runtime = resolve_chat_runtime_config(user)

    assert runtime.provider == "ollama"
    assert runtime.api_key is None
    assert runtime.key_source == "not_required"


def test_embedding_runtime_ignores_user_key_for_ollama() -> None:
    user = make_user(
        settings_json={
            "embeddingProvider": "ollama",
            "embeddingModel": "qwen3-embedding:0.6b",
            "embeddingApiUrl": "http://127.0.0.1:11434",
        },
        embedding_api_key_ciphertext="not-a-valid-fernet-token",
    )

    runtime = resolve_embedding_runtime_config(user)

    assert runtime.provider == "ollama"
    assert runtime.api_key is None
    assert runtime.key_source == "not_required"


@pytest.mark.asyncio
async def test_update_settings_reverts_model_and_search_to_defaults() -> None:
    user = make_user(
        settings_json={
            "modelProvider": "openai_compatible",
            "modelName": "gpt-4o-mini",
            "apiUrl": "https://example.com/v1",
            "searchProvider": "exa",
        },
        llm_api_key_ciphertext="ciphertext",
        llm_api_key_last4="1234",
        exa_api_key_ciphertext="ciphertext",
        exa_api_key_last4="5678",
    )
    session = DummySession()

    result = await update_settings(
        session,
        user=user,
        payload={
            "useDefaultModelConfig": True,
            "useDefaultSearchConfig": True,
        },
    )

    assert "modelProvider" not in user.settings_json
    assert "modelName" not in user.settings_json
    assert "apiUrl" not in user.settings_json
    assert "searchProvider" not in user.settings_json
    assert user.llm_api_key_ciphertext is None
    assert user.llm_api_key_last4 is None
    assert user.exa_api_key_ciphertext is None
    assert user.exa_api_key_last4 is None
    assert result["usingDefaultModelConfig"] is True
    assert result["usingDefaultSearchConfig"] is True
    assert session.commits == 1
    assert session.refreshed is user
