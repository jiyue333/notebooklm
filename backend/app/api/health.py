from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST

from app.api.response import success_response
from app.core.config import get_settings
from app.infra.mq.rocketmq_client import probe_rocketmq_client
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
    rocketmq_available, rocketmq_error = probe_rocketmq_client()
    return success_response(
        item={
            "status": "ready",
            "dependencies": {
                "database": "configured",
                "redis": "configured",
                "rocketmq": {
                    "endpoint": settings.rocketmq_proxy_endpoint,
                    "clientAvailable": rocketmq_available,
                    "error": rocketmq_error,
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
