"""Cache adapters."""
from app.infra.cache.cache_keys import (
    notebook_detail_key,
    search_session_key,
    settings_view_key,
    summary_cache_key,
)
from app.infra.cache.cache_service import delete_keys, get_json, set_json

__all__ = [
    "delete_keys",
    "get_json",
    "notebook_detail_key",
    "search_session_key",
    "set_json",
    "settings_view_key",
    "summary_cache_key",
]
