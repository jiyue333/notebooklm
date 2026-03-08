from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest

HTTP_REQUEST_COUNTER = Counter(
    "notebooklm_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION = Histogram(
    "notebooklm_http_request_duration_ms",
    "HTTP request duration in milliseconds",
    ["method", "path"],
)
JOB_EXECUTION_COUNTER = Counter(
    "notebooklm_jobs_total",
    "Worker job executions",
    ["job_type", "status"],
)


def observe_http_request(*, method: str, path: str, status_code: int, duration_ms: float) -> None:
    HTTP_REQUEST_COUNTER.labels(
        method=method,
        path=path,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION.labels(method=method, path=path).observe(duration_ms)


def observe_job(*, job_type: str, status: str) -> None:
    JOB_EXECUTION_COUNTER.labels(job_type=job_type, status=status).inc()


def render_metrics() -> bytes:
    return generate_latest()
