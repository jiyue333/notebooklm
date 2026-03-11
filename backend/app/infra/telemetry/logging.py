from __future__ import annotations

import logging

import structlog

from app.core.config import Settings, get_settings

_LOGGING_CONFIGURED = False

try:
    from opentelemetry import trace
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    trace = None


def setup_logging(settings: Settings | None = None) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(level=level, format="%(message)s")
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _inject_current_trace_context,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _LOGGING_CONFIGURED = True


def _inject_current_trace_context(_logger, _method_name, event_dict: dict) -> dict:
    if trace is None:
        return event_dict

    span = trace.get_current_span()
    if span is None:
        return event_dict

    context = span.get_span_context()
    if not context or not context.is_valid:
        return event_dict

    event_dict.setdefault("trace_id", format(context.trace_id, "032x"))
    event_dict.setdefault("span_id", format(context.span_id, "016x"))
    return event_dict
