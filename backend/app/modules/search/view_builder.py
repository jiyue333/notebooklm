from __future__ import annotations

from app.modules.search.models import SearchResult, SearchSession


def build_search_result_view(result: SearchResult) -> dict:
    return {
        "id": result.id,
        "title": result.title,
        "description": result.description or result.preview_markdown or "",
        "icon": "🌐",
        "url": result.raw_url,
        "selected": True,
    }


def build_search_session_view(search_session: SearchSession) -> dict:
    return {
        "searchSessionId": search_session.id,
        "mode": search_session.mode,
        "modeLabel": search_session.mode_label,
        "status": search_session.status,
        "execution": search_session.execution_mode,
    }


def build_search_response(
    search_session: SearchSession,
    results: list[SearchResult],
    *,
    meta: dict | None = None,
) -> dict:
    return {
        "item": build_search_session_view(search_session),
        "items": [build_search_result_view(result) for result in results],
        "meta": meta or {"provider": search_session.provider_name},
    }
