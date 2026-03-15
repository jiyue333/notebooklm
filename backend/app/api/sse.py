"""SSE (Server-Sent Events) encoding utilities."""

from __future__ import annotations

import json

from app.api.errors import AppError


def encode_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def build_sse_error_payload(
    exc: Exception,
    *,
    fallback_message: str,
    fallback_code: str,
    logger=None,
    log_event: str = "",
    **log_kwargs,
) -> str:
    if isinstance(exc, AppError):
        return encode_sse_event("error", {
            "message": exc.message,
            "code": exc.code,
            "status": exc.status_code,
            "meta": exc.meta,
        })
    if logger and log_event:
        logger.exception(log_event, **log_kwargs)
    detail = str(exc).strip()
    return encode_sse_event("error", {
        "message": fallback_message,
        "code": fallback_code,
        "status": 502,
        "meta": {
            "detail": detail[:500] if detail else "",
        },
    })
