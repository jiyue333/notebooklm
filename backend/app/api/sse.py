"""SSE (Server-Sent Events) encoding utilities."""

from __future__ import annotations

import json
import re

from app.api.errors import AppError


def encode_sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def iter_text_token_events(
    text: str,
    *,
    chunk_size: int = 24,
):
    """Yield SSE token events for incremental streaming.

    Splits text into chunks (by sentence, then by size) and yields each as
    a token event so the frontend can append and render progressively.
    """
    if not text or not text.strip():
        return
    sentences = re.split(r"(?<=[。！？.!?\n])\s*", text.strip())
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if len(sent) <= chunk_size:
            yield encode_sse_event("token", {"text": sent, "content": sent})
        else:
            for i in range(0, len(sent), chunk_size):
                chunk = sent[i : i + chunk_size]
                if chunk:
                    yield encode_sse_event("token", {"text": chunk, "content": chunk})


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
