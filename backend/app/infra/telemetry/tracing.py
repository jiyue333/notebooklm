from __future__ import annotations

import asyncio
import functools
import json
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.trace import Span as _Span

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    SQLAlchemyInstrumentor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    Status = None
    StatusCode = None

from app.core.config import Settings, get_settings

_TRACING_CONFIGURED = False


def resolve_otlp_trace_endpoint(settings: Settings | None = None) -> str | None:
    runtime_settings = settings or get_settings()
    endpoint = runtime_settings.otel_exporter_otlp_endpoint
    if not endpoint:
        return None

    parts = urlsplit(endpoint)
    path = parts.path.rstrip("/")
    if path.endswith("/v1/traces") or path == "/v1/traces":
        normalized_path = "/v1/traces"
    elif not path:
        normalized_path = "/v1/traces"
    else:
        normalized_path = f"{path}/v1/traces"
    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, parts.fragment))


def _build_trace_exporter(endpoint: str) -> Any:
    if OTLPSpanExporter is None:
        return None

    session = requests.Session()
    # Trace export targets a local collector in dev; ignore shell-wide proxies.
    session.trust_env = False
    return OTLPSpanExporter(endpoint=endpoint, session=session)


def setup_tracing(
    *,
    app: FastAPI | None = None,
    engine: AsyncEngine | None = None,
    settings: Settings | None = None,
) -> "_TracerProvider | None":
    global _TRACING_CONFIGURED
    if trace is None or TracerProvider is None or Resource is None:
        return None
    if _TRACING_CONFIGURED:
        return trace.get_tracer_provider()  # type: ignore[return-value]

    settings = settings or get_settings()
    if not settings.otel_enabled:
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.app_env,
            }
        )
    )
    exporter_endpoint = resolve_otlp_trace_endpoint(settings)
    if exporter_endpoint and BatchSpanProcessor is not None:
        exporter = _build_trace_exporter(exporter_endpoint)
    else:
        exporter = None
    if exporter is not None and BatchSpanProcessor is not None:
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)

    if app is not None and FastAPIInstrumentor is not None:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    if engine is not None and SQLAlchemyInstrumentor is not None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine,
            tracer_provider=provider,
        )

    _TRACING_CONFIGURED = True
    return provider


def shutdown_tracing() -> None:
    if trace is None:
        return
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()


def get_tracer(name: str = "notebooklm.business"):
    if trace is None:
        return None
    return trace.get_tracer(name)


@contextmanager
def start_span(name: str, *, attributes: dict | None = None):
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(name) as span:
        _apply_span_attributes(span, attributes or {})
        try:
            yield span
        except Exception as exc:
            _record_span_exception(span, exc)
            raise


def traced(span_name: str, *, attrs: dict | None = None) -> Callable:
    """装饰器：自动为函数创建 tracing span。

    用法::

        @traced("chat.route")
        async def route_chat_message(...):
            ...

        @traced("summary.finalize", attrs={"step": "finalize"})
        async def finalize_summary(...):
            ...
    """

    def decorator(fn: Callable) -> Callable:
        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                with start_span(span_name, attributes=attrs):
                    return await fn(*args, **kwargs)

            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            with start_span(span_name, attributes=attrs):
                return fn(*args, **kwargs)

        return sync_wrapper

    return decorator



def _apply_span_attributes(span: "_Span | None", attributes: dict) -> None:
    if span is None or not attributes:
        return
    for key, value in attributes.items():
        if value in (None, ""):
            continue
        if isinstance(value, (bool, int, float, str)):
            span.set_attribute(key, value)
        else:
            span.set_attribute(key, json.dumps(value, ensure_ascii=False))


def _record_span_exception(span: "_Span | None", exc: Exception) -> None:
    if span is None:
        return
    record_exception = getattr(span, "record_exception", None)
    if callable(record_exception):
        record_exception(exc)
    if Status is not None and StatusCode is not None:
        span.set_status(Status(StatusCode.ERROR, str(exc)))
