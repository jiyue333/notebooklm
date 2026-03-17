"""Structured logging configuration.

Key design decisions:
  - JSON mode: exception tracebacks are flattened into a single-line
    ``exc_text`` field so each log event is exactly one line (critical
    for Loki/Promtail ingestion).
  - Noisy loggers (uvicorn access, httpx, asyncpg) are silenced.
  - OTel trace context is injected when available.
  - Log fields are ordered: stable/correlation fields first (request_id,
    event, trace_id, span_id), then logger/level/timestamp, then HTTP
    context, then event-specific fields (alphabetically).
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

import structlog

from app.core.config import Settings, get_settings

_LOGGING_CONFIGURED = False

# Field order: most stable/correlation fields first for grep/jq/Loki.
_LOG_FIELD_ORDER = (
    "request_id",
    "event",
    "trace_id",
    "span_id",
    "logger",
    "level",
    "timestamp",
    "http_method",
    "http_path",
    "status_code",
    "duration_ms",
    "elapsed_ms",
    "search_session_id",
    "exc_type",
    "exc_message",
    "exc_text",
)

try:
    from opentelemetry import trace
except ModuleNotFoundError:
    trace = None

_NOISY_LOGGERS = (
    "uvicorn.access",
    "httpx",
    "httpcore",
    "asyncpg",
    "sqlalchemy.engine",
    "hpack",
)


def setup_logging(settings: Settings | None = None) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(level=level, format="%(message)s")
    if getattr(settings, "log_file", None):
        p = Path(settings.log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        # 行缓冲，每行立即刷盘，便于 Promtail 采集且重启前可见
        stream = open(p, "a", encoding="utf-8", buffering=1)
        root.addHandler(logging.StreamHandler(stream))
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _inject_current_trace_context,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.log_json:
        renderer = structlog.processors.JSONRenderer()
        exc_processor = _flatten_exception
    else:
        renderer = structlog.dev.ConsoleRenderer()
        exc_processor = structlog.processors.format_exc_info

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            exc_processor,
            _order_log_fields,
            renderer,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _LOGGING_CONFIGURED = True


def _order_log_fields(_logger, _method_name, event_dict: dict) -> dict:
    """Reorder event_dict keys: stable fields first, then rest alphabetically."""
    ordered: dict = {}
    for key in _LOG_FIELD_ORDER:
        if key in event_dict:
            ordered[key] = event_dict[key]
    for key in sorted(event_dict.keys()):
        if key not in ordered:
            ordered[key] = event_dict[key]
    return ordered


def _flatten_exception(_logger, _method_name, event_dict: dict) -> dict:
    """Collapse multi-line tracebacks into a single ``exc_text`` field.

    This ensures each JSON log line stays on one line in the log file,
    which is critical for Loki/Promtail line-based ingestion.
    """
    exc_info = event_dict.pop("exc_info", None)
    if exc_info is True:
        exc_info = None
    if exc_info:
        if isinstance(exc_info, BaseException):
            exc_info = (type(exc_info), exc_info, exc_info.__traceback__)
        if isinstance(exc_info, tuple):
            tb_lines = traceback.format_exception(*exc_info)
            flat = " | ".join(
                line.strip() for line in "".join(tb_lines).splitlines() if line.strip()
            )
            event_dict["exc_text"] = flat[:2000]
            event_dict["exc_type"] = exc_info[0].__name__ if exc_info[0] else ""
            event_dict["exc_message"] = str(exc_info[1])[:500] if exc_info[1] else ""
    return event_dict


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
