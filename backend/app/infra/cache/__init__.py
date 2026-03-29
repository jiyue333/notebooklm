"""Cache adapters."""
from app.infra.cache.cache_keys import (
    chat_web_search_key,
    notebook_detail_key,
    search_context_key,
    search_session_key,
    settings_view_key,
    summary_cache_key,
)
from app.infra.cache.cache_service import delete_keys, get_json, set_json

__all__ = [
    "delete_keys",
    "get_json",
    "chat_web_search_key",
    "notebook_detail_key",
    "search_context_key",
    "search_session_key",
    "set_json",
    "settings_view_key",
    "summary_cache_key",
]
