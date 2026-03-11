from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest

LATENCY_MS_BUCKETS = (
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    30000,
    60000,
    120000,
    300000,
)
CHUNK_COUNT_BUCKETS = (
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
    512,
    1024,
)

HTTP_REQUEST_COUNTER = Counter(
    "notebooklm_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)
HTTP_REQUEST_DURATION = Histogram(
    "notebooklm_http_request_duration_ms",
    "HTTP request duration in milliseconds",
    ["method", "path"],
    buckets=LATENCY_MS_BUCKETS,
)
JOB_EXECUTION_COUNTER = Counter(
    "notebooklm_jobs_total",
    "Worker job executions",
    ["job_type", "status"],
)
SEARCH_REQUEST_COUNTER = Counter(
    "notebooklm_search_requests_total",
    "Search requests by mode and execution path",
    ["mode", "execution", "status"],
)
SEARCH_PROVIDER_DURATION = Histogram(
    "notebooklm_search_provider_duration_ms",
    "Search provider duration in milliseconds",
    ["provider", "mode", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
SOURCE_IMPORT_COUNTER = Counter(
    "notebooklm_source_import_total",
    "Imported or skipped sources",
    ["source_type", "result"],
)
INGEST_PARSE_COUNTER = Counter(
    "notebooklm_ingest_parse_total",
    "Ingest parse outcomes",
    ["input_type", "status", "parser", "error_tag"],
)
INGEST_FALLBACK_COUNTER = Counter(
    "notebooklm_ingest_fallback_total",
    "Fallback usage during ingest",
    ["fallback_type"],
)
INGEST_CHUNK_COUNT = Histogram(
    "notebooklm_ingest_chunk_count",
    "Chunk count per ingested article",
    ["input_type"],
    buckets=CHUNK_COUNT_BUCKETS,
)
INGEST_READY_DURATION = Histogram(
    "notebooklm_ingest_ready_duration_ms",
    "Time from article creation to content-ready in milliseconds",
    ["input_type"],
    buckets=LATENCY_MS_BUCKETS,
)
LLM_CALL_COUNTER = Counter(
    "notebooklm_llm_calls_total",
    "LLM calls by operation and status",
    ["operation", "provider", "model", "status"],
)
LLM_CALL_DURATION = Histogram(
    "notebooklm_llm_call_duration_ms",
    "LLM call latency in milliseconds",
    ["operation", "provider", "model", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
LLM_TOKEN_COUNTER = Counter(
    "notebooklm_llm_tokens_total",
    "LLM token usage",
    ["operation", "provider", "model", "token_type"],
)
SCHEDULER_ACTION_COUNTER = Counter(
    "notebooklm_scheduler_actions_total",
    "Scheduler actions by category",
    ["action"],
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


def observe_search_request(*, mode: str, execution: str, status: str) -> None:
    SEARCH_REQUEST_COUNTER.labels(mode=mode, execution=execution, status=status).inc()


def observe_search_provider(*, provider: str, mode: str, status: str, duration_ms: float) -> None:
    SEARCH_PROVIDER_DURATION.labels(provider=provider, mode=mode, status=status).observe(duration_ms)


def observe_source_import(*, source_type: str, result: str, count: int = 1) -> None:
    SOURCE_IMPORT_COUNTER.labels(source_type=source_type, result=result).inc(count)


def observe_ingest_parse(*, input_type: str, status: str, parser: str, error_tag: str = "none") -> None:
    INGEST_PARSE_COUNTER.labels(
        input_type=input_type,
        status=status,
        parser=parser,
        error_tag=error_tag,
    ).inc()


def observe_ingest_fallback(*, fallback_type: str) -> None:
    INGEST_FALLBACK_COUNTER.labels(fallback_type=fallback_type).inc()


def observe_ingest_chunks(*, input_type: str, chunk_count: int) -> None:
    INGEST_CHUNK_COUNT.labels(input_type=input_type).observe(chunk_count)


def observe_ingest_ready(*, input_type: str, duration_ms: float) -> None:
    INGEST_READY_DURATION.labels(input_type=input_type).observe(duration_ms)


def observe_llm_call(
    *,
    operation: str,
    provider: str,
    model: str,
    status: str,
    duration_ms: float,
    usage: dict[str, int] | None = None,
) -> None:
    LLM_CALL_COUNTER.labels(operation=operation, provider=provider, model=model, status=status).inc()
    LLM_CALL_DURATION.labels(
        operation=operation,
        provider=provider,
        model=model,
        status=status,
    ).observe(duration_ms)
    usage = usage or {}
    for token_type in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = int(usage.get(token_type, 0) or 0)
        if value:
            LLM_TOKEN_COUNTER.labels(
                operation=operation,
                provider=provider,
                model=model,
                token_type=token_type,
            ).inc(value)


def observe_scheduler_action(*, action: str, count: int) -> None:
    if count:
        SCHEDULER_ACTION_COUNTER.labels(action=action).inc(count)


def render_metrics() -> bytes:
    return generate_latest()
