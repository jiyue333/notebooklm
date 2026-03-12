from __future__ import annotations

KEY_PREFIX = "notebooklm"


def notebook_detail_key(*, user_id: str, notebook_id: str) -> str:
    return f"{KEY_PREFIX}:notebook_detail:{user_id}:{notebook_id}"


def search_session_key(*, user_id: str, notebook_id: str, search_session_id: str) -> str:
    return f"{KEY_PREFIX}:search_session:{user_id}:{notebook_id}:{search_session_id}"


def settings_view_key(*, user_id: str) -> str:
    return f"{KEY_PREFIX}:settings_view:{user_id}"


def summary_cache_key(
    *,
    article_id: str,
    content_hash: str,
    prompt_version: str,
    model_provider: str,
    model_name: str,
    output_language: str,
) -> str:
    return (
        f"{KEY_PREFIX}:summary:{article_id}:{content_hash}:"
        f"{prompt_version}:{model_provider}:{model_name}:{output_language}"
    )
