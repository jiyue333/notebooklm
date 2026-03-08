from __future__ import annotations

from typing import TYPE_CHECKING

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
    if settings.otel_exporter_otlp_endpoint and OTLPSpanExporter is not None and BatchSpanProcessor is not None:
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
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
