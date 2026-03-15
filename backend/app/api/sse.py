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
    """统一的 SSE 错误 event 构造。

    对 AppError 直接序列化；对其他异常使用 fallback 信息，
    并在提供 logger 时记录异常日志。
    """
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


def extract_stream_text(chunk) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content or "")
