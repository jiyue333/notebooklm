from __future__ import annotations

import os
from functools import lru_cache

from app.core.config import Settings, get_settings


def configure_langsmith(settings: Settings | None = None) -> None:
    runtime_settings = settings or get_settings()
    client_enabled = bool(runtime_settings.langsmith_enabled and runtime_settings.langsmith_api_key)
    tracing_enabled = bool(client_enabled and runtime_settings.langsmith_tracing)

    _set_or_clear_env("LANGSMITH_API_KEY", runtime_settings.langsmith_api_key if client_enabled else None)
    _set_or_clear_env("LANGSMITH_ENDPOINT", runtime_settings.langsmith_endpoint if client_enabled else None)
    _set_or_clear_env("LANGSMITH_PROJECT", runtime_settings.langsmith_project if client_enabled else None)
    _set_or_clear_env("LANGSMITH_WORKSPACE_ID", runtime_settings.langsmith_workspace_id if client_enabled else None)
    _set_or_clear_env("LANGSMITH_TRACING", "true" if tracing_enabled else "false")

    _set_or_clear_env("LANGCHAIN_TRACING_V2", "true" if tracing_enabled else "false")
    _set_or_clear_env("LANGCHAIN_PROJECT", runtime_settings.langsmith_project if client_enabled else None)


def _set_or_clear_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
        return
    os.environ[name] = value


