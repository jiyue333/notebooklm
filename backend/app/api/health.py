from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.api.response import success_response
from app.core.config import get_settings
from app.infra.cache.redis_client import get_redis_factory
from app.infra.mq.kafka_client import probe_kafka_broker, probe_kafka_client
from app.infra.telemetry.metrics import render_metrics
from app.infra.telemetry.tracing import resolve_otlp_trace_endpoint

router = APIRouter(tags=["system"])


@router.get("/health")
async def health_check() -> dict:
    settings = get_settings()
    return success_response(
        item={
            "status": "ok",
            "service": settings.app_name,
            "environment": settings.app_env,
        }
    )


@router.get("/ready")
async def readiness_check() -> dict:
    settings = get_settings()
    redis_reachable = False
    redis_error = None
    if settings.redis_cache_enabled:
        try:
            redis_reachable = await get_redis_factory().ping()
        except Exception as exc:
            redis_error = str(exc)
    kafka_available, kafka_error = probe_kafka_client()
    broker_reachable, broker_error = await probe_kafka_broker(settings)
    return success_response(
        item={
            "status": "ready",
            "dependencies": {
                "database": "configured",
                "redis": {
                    "enabled": settings.redis_cache_enabled,
                    "url": settings.redis_url,
                    "reachable": redis_reachable if settings.redis_cache_enabled else None,
                    "error": redis_error,
                },
                "kafka": {
                    "bootstrapServers": settings.kafka_bootstrap_servers,
                    "clientAvailable": kafka_available,
                    "brokerReachable": broker_reachable,
                    "error": kafka_error or broker_error,
                },
                "objectStorage": settings.object_storage_bucket,
                "searchCredentialSource": "database",
                "tracing": {
                    "enabled": settings.otel_enabled,
                    "traceExporterEndpoint": resolve_otlp_trace_endpoint(settings),
                },
            },
        }
    )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)
