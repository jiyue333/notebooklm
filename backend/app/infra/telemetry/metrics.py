from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, generate_latest, start_http_server

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
RESULT_COUNT_BUCKETS = (
    1,
    2,
    5,
    10,
    20,
    50,
    100,
)
TEXT_LENGTH_BUCKETS = (
    50,
    100,
    200,
    400,
    800,
    1600,
    3200,
    6400,
    12800,
)
QUALITY_SCORE_BUCKETS = (
    0.1,
    0.2,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
    1.0,
)
_STARTED_PORTS: set[tuple[str, int]] = set()

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
SEARCH_STAGE_DURATION = Histogram(
    "notebooklm_search_stage_duration_ms",
    "Search stage duration in milliseconds",
    ["stage", "mode", "execution", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
SEARCH_RESULT_COUNT = Histogram(
    "notebooklm_search_result_count",
    "Search result count per completed session",
    ["mode", "execution"],
    buckets=RESULT_COUNT_BUCKETS,
)
SEARCH_RESULT_SCORE = Histogram(
    "notebooklm_search_result_score",
    "Search result quality scores",
    ["score_type", "mode", "execution", "provider"],
    buckets=QUALITY_SCORE_BUCKETS,
)
SEARCH_RESULT_SIGNAL_COUNTER = Counter(
    "notebooklm_search_result_signal_total",
    "Search result quality signals",
    ["signal", "mode", "execution", "provider", "result"],
)
SEARCH_REVIEW_SAMPLE_COUNTER = Counter(
    "notebooklm_search_review_samples_total",
    "Sampled search review capture results",
    ["mode", "execution", "provider", "review_mode", "result"],
)
SEARCH_REVIEW_SCORE = Histogram(
    "notebooklm_search_review_score",
    "LLM search review scores",
    ["mode", "execution", "provider", "reviewer", "score_type"],
    buckets=QUALITY_SCORE_BUCKETS,
)
SEARCH_REVIEW_BAD_CASE_COUNTER = Counter(
    "notebooklm_search_review_bad_cases_total",
    "Flagged search bad cases",
    ["mode", "execution", "provider", "reviewer", "reason"],
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
INGEST_STAGE_DURATION = Histogram(
    "notebooklm_ingest_stage_duration_ms",
    "Ingest stage duration in milliseconds",
    ["stage", "input_type", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
INGEST_QUALITY_SCORE = Histogram(
    "notebooklm_ingest_markdown_quality_score",
    "Markdown quality score distribution",
    ["input_type"],
    buckets=QUALITY_SCORE_BUCKETS,
)
INGEST_STRUCTURE_SCORE = Histogram(
    "notebooklm_ingest_structure_score",
    "Markdown structure quality scores",
    ["input_type", "structure_type"],
    buckets=QUALITY_SCORE_BUCKETS,
)
INGEST_DOC_TYPE_COUNTER = Counter(
    "notebooklm_ingest_doc_type_total",
    "Ingest outcomes by document type",
    ["doc_type", "status"],
)
INGEST_DOC_TYPE_QUALITY_SCORE = Histogram(
    "notebooklm_ingest_doc_type_quality_score",
    "Markdown quality scores by document type",
    ["doc_type"],
    buckets=QUALITY_SCORE_BUCKETS,
)
INGEST_DOC_TYPE_STRUCTURE_SCORE = Histogram(
    "notebooklm_ingest_doc_type_structure_score",
    "Markdown structure quality scores by document type",
    ["doc_type", "structure_type"],
    buckets=QUALITY_SCORE_BUCKETS,
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
AI_REQUEST_COUNTER = Counter(
    "notebooklm_ai_requests_total",
    "AI request outcomes",
    ["operation", "mode", "status"],
)
AI_REQUEST_DURATION = Histogram(
    "notebooklm_ai_request_duration_ms",
    "End-to-end AI request duration in milliseconds",
    ["operation", "mode", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
AI_FIRST_TOKEN_DURATION = Histogram(
    "notebooklm_ai_first_token_ms",
    "Time to first token in milliseconds",
    ["operation", "provider", "model"],
    buckets=LATENCY_MS_BUCKETS,
)
AI_STREAM_DURATION = Histogram(
    "notebooklm_ai_token_stream_duration_ms",
    "AI token stream duration in milliseconds",
    ["operation", "provider", "model", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
AI_ROUTE_COUNTER = Counter(
    "notebooklm_ai_route_total",
    "AI route distribution",
    ["operation", "route"],
)
AI_RETRIEVAL_CONTEXT_COUNT = Histogram(
    "notebooklm_ai_retrieval_context_count",
    "Retrieved context count used by AI generation",
    ["operation", "route", "context_type"],
    buckets=CHUNK_COUNT_BUCKETS,
)
AI_CACHE_LOOKUP_COUNTER = Counter(
    "notebooklm_ai_cache_lookup_total",
    "AI cache lookup results",
    ["operation", "cache_layer", "result"],
)
AI_RESPONSE_LENGTH = Histogram(
    "notebooklm_ai_answer_length_chars",
    "AI answer length in characters",
    ["operation"],
    buckets=TEXT_LENGTH_BUCKETS,
)
AI_USER_ACTION_COUNTER = Counter(
    "notebooklm_ai_user_actions_total",
    "AI user interaction signals",
    ["operation", "action", "route"],
)
AI_ONLINE_REVIEW_COUNTER = Counter(
    "notebooklm_ai_online_review_total",
    "AI online review outcomes",
    ["operation", "route", "reviewer", "result"],
)
AI_ONLINE_REVIEW_SCORE = Histogram(
    "notebooklm_ai_online_review_score",
    "AI online review scores",
    ["operation", "route", "reviewer", "score_type"],
    buckets=QUALITY_SCORE_BUCKETS,
)
AI_ONLINE_REVIEW_BAD_CASE_COUNTER = Counter(
    "notebooklm_ai_online_review_bad_cases_total",
    "Flagged AI online review bad cases",
    ["operation", "route", "reviewer", "reason"],
)
REDIS_INSPECTION_COUNTER = Counter(
    "notebooklm_redis_inspection_runs_total",
    "Redis inspection run outcomes",
    ["result"],
)
REDIS_INSPECTION_KEYS_SCANNED = Gauge(
    "notebooklm_redis_inspection_keys_scanned",
    "Number of Redis keys inspected during the latest run",
)
REDIS_BIGKEY_COUNT = Gauge(
    "notebooklm_redis_bigkey_count",
    "Number of detected Redis bigkeys in the latest inspection",
)
REDIS_BIGGEST_KEY_BYTES = Gauge(
    "notebooklm_redis_biggest_key_bytes",
    "Size in bytes of the largest Redis key detected in the latest inspection",
)
REDIS_HOTKEY_COUNT = Gauge(
    "notebooklm_redis_hotkey_count",
    "Number of detected Redis hotkeys in the latest inspection",
)
REDIS_HOTTEST_FREQUENCY = Gauge(
    "notebooklm_redis_hottest_key_frequency",
    "Frequency score of the hottest Redis key detected in the latest inspection",
)
REDIS_INSPECTION_LAST_SUCCESS_TS = Gauge(
    "notebooklm_redis_inspection_last_success_unixtime",
    "Unix timestamp of the most recent successful Redis inspection",
)
SCHEDULER_ACTION_COUNTER = Counter(
    "notebooklm_scheduler_actions_total",
    "Scheduler actions by category",
    ["action"],
)
MQ_PUBLISH_COUNTER = Counter(
    "notebooklm_mq_publish_total",
    "Message publish outcomes",
    ["topic", "tag", "status"],
)
MQ_PUBLISH_DURATION = Histogram(
    "notebooklm_mq_publish_duration_ms",
    "Message publish latency in milliseconds",
    ["topic", "tag", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
MQ_CONSUME_COUNTER = Counter(
    "notebooklm_mq_consume_total",
    "Message consume outcomes",
    ["topic", "tag", "status"],
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


def observe_search_stage(*, stage: str, mode: str, execution: str, status: str, duration_ms: float) -> None:
    SEARCH_STAGE_DURATION.labels(
        stage=stage,
        mode=mode,
        execution=execution,
        status=status,
    ).observe(duration_ms)


def observe_search_result_count(*, mode: str, execution: str, result_count: int) -> None:
    SEARCH_RESULT_COUNT.labels(mode=mode, execution=execution).observe(result_count)


def observe_search_result_score(
    *,
    score_type: str,
    mode: str,
    execution: str,
    provider: str,
    score: float,
) -> None:
    SEARCH_RESULT_SCORE.labels(
        score_type=score_type,
        mode=mode,
        execution=execution,
        provider=provider,
    ).observe(score)


def observe_search_result_signal(
    *,
    signal: str,
    mode: str,
    execution: str,
    provider: str,
    result: str,
    count: int = 1,
) -> None:
    SEARCH_RESULT_SIGNAL_COUNTER.labels(
        signal=signal,
        mode=mode,
        execution=execution,
        provider=provider,
        result=result,
    ).inc(count)


def observe_search_review_sample(
    *,
    mode: str,
    execution: str,
    provider: str,
    review_mode: str,
    result: str,
    count: int = 1,
) -> None:
    SEARCH_REVIEW_SAMPLE_COUNTER.labels(
        mode=mode,
        execution=execution,
        provider=provider,
        review_mode=review_mode,
        result=result,
    ).inc(count)


def observe_search_review_score(
    *,
    mode: str,
    execution: str,
    provider: str,
    reviewer: str,
    score_type: str,
    score: float,
) -> None:
    SEARCH_REVIEW_SCORE.labels(
        mode=mode,
        execution=execution,
        provider=provider,
        reviewer=reviewer,
        score_type=score_type,
    ).observe(score)


def observe_search_review_bad_case(
    *,
    mode: str,
    execution: str,
    provider: str,
    reviewer: str,
    reason: str,
    count: int = 1,
) -> None:
    SEARCH_REVIEW_BAD_CASE_COUNTER.labels(
        mode=mode,
        execution=execution,
        provider=provider,
        reviewer=reviewer,
        reason=reason,
    ).inc(count)


def observe_source_import(*, source_type: str, result: str, count: int = 1) -> None:
    SOURCE_IMPORT_COUNTER.labels(source_type=source_type, result=result).inc(count)


def observe_ingest_parse(*, input_type: str, status: str, parser: str, error_tag: str = "none") -> None:
    INGEST_PARSE_COUNTER.labels(
        input_type=input_type,
        status=status,
        parser=parser,
        error_tag=error_tag,
    ).inc()


def observe_ingest_doc_type(*, doc_type: str, status: str, count: int = 1) -> None:
    INGEST_DOC_TYPE_COUNTER.labels(doc_type=doc_type, status=status).inc(count)


def observe_ingest_fallback(*, fallback_type: str) -> None:
    INGEST_FALLBACK_COUNTER.labels(fallback_type=fallback_type).inc()


def observe_ingest_chunks(*, input_type: str, chunk_count: int) -> None:
    INGEST_CHUNK_COUNT.labels(input_type=input_type).observe(chunk_count)


def observe_ingest_ready(*, input_type: str, duration_ms: float) -> None:
    INGEST_READY_DURATION.labels(input_type=input_type).observe(duration_ms)


def observe_ingest_stage(*, stage: str, input_type: str, status: str, duration_ms: float) -> None:
    INGEST_STAGE_DURATION.labels(stage=stage, input_type=input_type, status=status).observe(duration_ms)


def observe_ingest_quality_score(*, input_type: str, score: float) -> None:
    INGEST_QUALITY_SCORE.labels(input_type=input_type).observe(score)


def observe_ingest_doc_type_quality_score(*, doc_type: str, score: float) -> None:
    INGEST_DOC_TYPE_QUALITY_SCORE.labels(doc_type=doc_type).observe(score)


def observe_ingest_structure_score(*, input_type: str, structure_type: str, score: float) -> None:
    INGEST_STRUCTURE_SCORE.labels(input_type=input_type, structure_type=structure_type).observe(score)


def observe_ingest_doc_type_structure_score(*, doc_type: str, structure_type: str, score: float) -> None:
    INGEST_DOC_TYPE_STRUCTURE_SCORE.labels(doc_type=doc_type, structure_type=structure_type).observe(score)


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


def observe_ai_request(*, operation: str, mode: str, status: str, duration_ms: float) -> None:
    AI_REQUEST_COUNTER.labels(operation=operation, mode=mode, status=status).inc()
    AI_REQUEST_DURATION.labels(operation=operation, mode=mode, status=status).observe(duration_ms)


def observe_ai_first_token(*, operation: str, provider: str, model: str, duration_ms: float) -> None:
    AI_FIRST_TOKEN_DURATION.labels(operation=operation, provider=provider, model=model).observe(duration_ms)


def observe_ai_stream(*, operation: str, provider: str, model: str, status: str, duration_ms: float) -> None:
    AI_STREAM_DURATION.labels(
        operation=operation,
        provider=provider,
        model=model,
        status=status,
    ).observe(duration_ms)


def observe_ai_route(*, operation: str, route: str) -> None:
    AI_ROUTE_COUNTER.labels(operation=operation, route=route).inc()


def observe_ai_retrieval_context(*, operation: str, route: str, context_type: str, count: int) -> None:
    AI_RETRIEVAL_CONTEXT_COUNT.labels(
        operation=operation,
        route=route,
        context_type=context_type,
    ).observe(count)


def observe_ai_cache_lookup(*, operation: str, cache_layer: str, result: str) -> None:
    AI_CACHE_LOOKUP_COUNTER.labels(
        operation=operation,
        cache_layer=cache_layer,
        result=result,
    ).inc()


def observe_ai_response_length(*, operation: str, length: int) -> None:
    AI_RESPONSE_LENGTH.labels(operation=operation).observe(length)


def observe_ai_user_action(*, operation: str, action: str, route: str = "none", count: int = 1) -> None:
    AI_USER_ACTION_COUNTER.labels(operation=operation, action=action, route=route or "none").inc(count)


def observe_ai_online_review_result(
    *,
    operation: str,
    route: str,
    reviewer: str,
    result: str,
    count: int = 1,
) -> None:
    AI_ONLINE_REVIEW_COUNTER.labels(
        operation=operation,
        route=route,
        reviewer=reviewer,
        result=result,
    ).inc(count)


def observe_ai_online_review_score(
    *,
    operation: str,
    route: str,
    reviewer: str,
    score_type: str,
    score: float,
) -> None:
    AI_ONLINE_REVIEW_SCORE.labels(
        operation=operation,
        route=route,
        reviewer=reviewer,
        score_type=score_type,
    ).observe(score)


def observe_ai_online_review_bad_case(
    *,
    operation: str,
    route: str,
    reviewer: str,
    reason: str,
    count: int = 1,
) -> None:
    AI_ONLINE_REVIEW_BAD_CASE_COUNTER.labels(
        operation=operation,
        route=route,
        reviewer=reviewer,
        reason=reason,
    ).inc(count)


def observe_redis_inspection(
    *,
    result: str,
    keys_scanned: int = 0,
    bigkey_count: int = 0,
    biggest_key_bytes: int = 0,
    hotkey_count: int = 0,
    hottest_frequency: int = 0,
    completed_at_unix: float | None = None,
) -> None:
    REDIS_INSPECTION_COUNTER.labels(result=result).inc()
    if result == "success":
        REDIS_INSPECTION_KEYS_SCANNED.set(keys_scanned)
        REDIS_BIGKEY_COUNT.set(bigkey_count)
        REDIS_BIGGEST_KEY_BYTES.set(biggest_key_bytes)
        REDIS_HOTKEY_COUNT.set(hotkey_count)
        REDIS_HOTTEST_FREQUENCY.set(hottest_frequency)
        if completed_at_unix is not None:
            REDIS_INSPECTION_LAST_SUCCESS_TS.set(completed_at_unix)


def observe_scheduler_action(*, action: str, count: int) -> None:
    if count:
        SCHEDULER_ACTION_COUNTER.labels(action=action).inc(count)


def observe_mq_publish(*, topic: str, tag: str, status: str, duration_ms: float) -> None:
    MQ_PUBLISH_COUNTER.labels(topic=topic, tag=tag, status=status).inc()
    MQ_PUBLISH_DURATION.labels(topic=topic, tag=tag, status=status).observe(duration_ms)


def observe_mq_consume(*, topic: str, tag: str, status: str) -> None:
    MQ_CONSUME_COUNTER.labels(topic=topic, tag=tag, status=status).inc()


def ensure_metrics_server(*, port: int, addr: str = "127.0.0.1") -> None:
    key = (addr, port)
    if key in _STARTED_PORTS:
        return
    start_http_server(port, addr=addr)
    _STARTED_PORTS.add(key)


def render_metrics() -> bytes:
    return generate_latest()
