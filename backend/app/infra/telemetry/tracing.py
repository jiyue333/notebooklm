from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit, urlunsplit

import requests

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider

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
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    trace = None
    OTLPSpanExporter = None
    FastAPIInstrumentor = None
    SQLAlchemyInstrumentor = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None

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


def _build_trace_exporter(endpoint: str) -> OTLPSpanExporter | None:
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
