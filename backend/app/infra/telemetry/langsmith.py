from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings


@lru_cache
def get_langsmith_client():
    settings = get_settings()
    if not settings.langsmith_enabled:
        return None
    if not settings.langsmith_api_key:
        return None

    from langsmith import Client

    return Client(
        api_key=settings.langsmith_api_key,
        api_url=settings.langsmith_endpoint,
    )
