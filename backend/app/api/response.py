from __future__ import annotations

from typing import Any


def success_response(
    *,
    item: Any = None,
    items: list[Any] | None = None,
    message: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "item": item,
        "items": items or [],
        "message": message,
        "meta": meta or {},
    }


def error_response(message: str, *, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "success": False,
        "item": None,
        "items": [],
        "message": message,
        "meta": meta or {},
    }
