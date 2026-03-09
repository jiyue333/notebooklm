from __future__ import annotations

import json

import structlog

try:
    from opentelemetry import trace
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    trace = None


def bind_observability_context(**fields) -> None:
    values = {key: value for key, value in fields.items() if value not in (None, "")}
    trace_id = get_current_trace_id()
    if trace_id:
        values.setdefault("trace_id", trace_id)
    if values:
        structlog.contextvars.bind_contextvars(**values)
        _set_span_attributes(values)


def get_current_trace_id() -> str | None:
    if trace is None:
        return None
    span = trace.get_current_span()
    if span is None:
        return None
    context = span.get_span_context()
    if not context or not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def _set_span_attributes(fields: dict) -> None:
    if trace is None:
        return
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    for key, value in fields.items():
        if isinstance(value, (bool, int, float, str)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, json.dumps(value, ensure_ascii=False))
