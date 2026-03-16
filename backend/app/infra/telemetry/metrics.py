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
# ── ADR-001 Search Pipeline Metrics ────────────────────────────────────────
SEARCH_PIPELINE_E2E = Histogram(
    "notebooklm_search_e2e_duration_ms",
    "Search pipeline end-to-end latency",
    ["mode"],
    buckets=LATENCY_MS_BUCKETS,
)
SEARCH_STAGE_DURATION = Histogram(
    "notebooklm_search_stage_duration_ms",
    "Per-stage latency in the search pipeline",
    ["stage", "mode", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
SEARCH_PARTIAL_FAILURE = Counter(
    "notebooklm_search_partial_failure_total",
    "Recall families that failed while others succeeded",
    ["mode"],
)
SEARCH_DEDUP_COUNTER = Counter(
    "notebooklm_search_dedup_total",
    "Canonicalization dedup hits",
    ["mode", "dedup_type"],
)
SEARCH_EMPTY_SLATE = Counter(
    "notebooklm_search_empty_slate_total",
    "Searches that produced an empty or low-confidence slate",
    ["mode", "reason"],
)
SEARCH_SLATE_CARD_COUNT = Histogram(
    "notebooklm_search_slate_card_count",
    "Number of cards in the served slate",
    ["mode"],
    buckets=RESULT_COUNT_BUCKETS,
)
SEARCH_AUTHORITY_PROXY = Histogram(
    "notebooklm_search_authority_proxy_at10",
    "Fraction of tier-1 authority sources in top 10",
    ["mode"],
    buckets=QUALITY_SCORE_BUCKETS,
)
SEARCH_DIVERSITY_PROXY = Histogram(
    "notebooklm_search_diversity_proxy_at10",
    "Source-type entropy in top 10 results",
    ["mode"],
    buckets=QUALITY_SCORE_BUCKETS,
)
SEARCH_NOVELTY_PROXY = Histogram(
    "notebooklm_search_novelty_proxy_at10",
    "Fraction of results novel to notebook in top 10",
    ["mode"],
    buckets=QUALITY_SCORE_BUCKETS,
)
# ── ADR-002 Ingest Pipeline Metrics ────────────────────────────────────────
INGEST_PIPELINE_E2E = Histogram(
    "notebooklm_ingest_e2e_duration_ms",
    "Ingest pipeline end-to-end latency",
    ["input_type"],
    buckets=LATENCY_MS_BUCKETS,
)
INGEST_STAGE_DURATION = Histogram(
    "notebooklm_ingest_stage_duration_ms",
    "Per-stage latency in the ingest pipeline",
    ["stage", "input_type", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
INGEST_FETCH_LATENCY = Histogram(
    "notebooklm_ingest_fetch_duration_ms",
    "Fetch latency by input type and content type",
    ["input_type", "content_type"],
    buckets=LATENCY_MS_BUCKETS,
)
INGEST_ROUTE_DISTRIBUTION = Counter(
    "notebooklm_ingest_route_total",
    "Document type routing distribution",
    ["input_type", "category"],
)
INGEST_PARSE_SUCCESS = Counter(
    "notebooklm_ingest_parse_result_total",
    "Parser success/failure by parser name",
    ["input_type", "parser", "result"],
)
INGEST_FALLBACK_RATE = Counter(
    "notebooklm_ingest_fallback_total",
    "Fallback triggers in ingest pipeline",
    ["input_type", "trigger"],
)
INGEST_SYNTHETIC_TOC = Counter(
    "notebooklm_ingest_toc_total",
    "TOC generation outcomes",
    ["input_type", "result"],
)
INGEST_BLOCK_COMPLETENESS = Counter(
    "notebooklm_ingest_block_type_total",
    "Block type counts in built block graphs",
    ["input_type", "block_type"],
)
# ── ADR-003 Summary Pipeline Metrics ──────────────────────────────────────
SUMMARY_PIPELINE_E2E = Histogram(
    "notebooklm_summary_e2e_duration_ms",
    "Summary pipeline end-to-end latency",
    [],
    buckets=LATENCY_MS_BUCKETS,
)
SUMMARY_STAGE_DURATION = Histogram(
    "notebooklm_summary_stage_duration_ms",
    "Per-stage latency in the summary pipeline",
    ["stage", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
SUMMARY_ROUTE_MIX = Counter(
    "notebooklm_summary_route_total",
    "Summary route distribution (S/M/L/X)",
    ["route"],
)
SUMMARY_JUDGE_REJECT = Counter(
    "notebooklm_summary_judge_reject_total",
    "Summary candidates rejected by judge",
    ["reason"],
)
SUMMARY_FALLBACK = Counter(
    "notebooklm_summary_fallback_total",
    "Summary fallback triggers",
    ["trigger"],
)
SUMMARY_CACHE_HIT = Counter(
    "notebooklm_summary_cache_hit_total",
    "Summary cache hits",
    [],
)
# ── ADR-004 Chat Pipeline Metrics ───────────────────────────────────────
CHAT_PIPELINE_E2E = Histogram(
    "notebooklm_chat_e2e_duration_ms",
    "Chat pipeline end-to-end latency",
    [],
    buckets=LATENCY_MS_BUCKETS,
)
CHAT_STAGE_DURATION = Histogram(
    "notebooklm_chat_stage_duration_ms",
    "Per-stage latency in the chat pipeline",
    ["stage", "route", "status"],
    buckets=LATENCY_MS_BUCKETS,
)
CHAT_ROUTE_MIX = Counter(
    "notebooklm_chat_route_total",
    "Chat route distribution (article_grounded/general/recommendation/notebook_research/ambiguous)",
    ["route"],
)
CHAT_FALLBACK = Counter(
    "notebooklm_chat_fallback_total",
    "Chat fallback triggers",
    ["reason"],
)
CHAT_EVIDENCE_COVERAGE = Histogram(
    "notebooklm_chat_evidence_coverage",
    "Evidence coverage in verified answers (0-1)",
    ["route"],
    buckets=QUALITY_SCORE_BUCKETS,
)
CHAT_RETRIEVAL_EVIDENCE_COUNT = Histogram(
    "notebooklm_chat_retrieval_evidence_count",
    "Number of evidence chunks retrieved",
    ["route"],
    buckets=RESULT_COUNT_BUCKETS,
)
CHAT_RETRIEVAL_RECOMMENDATION_COUNT = Histogram(
    "notebooklm_chat_retrieval_recommendation_count",
    "Number of recommended articles retrieved",
    ["route"],
    buckets=RESULT_COUNT_BUCKETS,
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


def observe_search_e2e(*, mode: str, duration_ms: float) -> None:
    SEARCH_PIPELINE_E2E.labels(mode=mode).observe(duration_ms)


def observe_search_stage(*, stage: str, mode: str, status: str, duration_ms: float) -> None:
    SEARCH_STAGE_DURATION.labels(stage=stage, mode=mode, status=status).observe(duration_ms)



def observe_search_partial_failure(*, mode: str) -> None:
    SEARCH_PARTIAL_FAILURE.labels(mode=mode).inc()


def observe_search_dedup(*, mode: str, dedup_type: str, count: int = 1) -> None:
    SEARCH_DEDUP_COUNTER.labels(mode=mode, dedup_type=dedup_type).inc(count)


def observe_search_empty_slate(*, mode: str, reason: str) -> None:
    SEARCH_EMPTY_SLATE.labels(mode=mode, reason=reason).inc()


def observe_search_slate_card_count(*, mode: str, count: int) -> None:
    SEARCH_SLATE_CARD_COUNT.labels(mode=mode).observe(count)


def observe_search_authority_proxy(*, mode: str, ratio: float) -> None:
    SEARCH_AUTHORITY_PROXY.labels(mode=mode).observe(ratio)


def observe_search_diversity_proxy(*, mode: str, entropy: float) -> None:
    SEARCH_DIVERSITY_PROXY.labels(mode=mode).observe(entropy)


def observe_search_novelty_proxy(*, mode: str, ratio: float) -> None:
    SEARCH_NOVELTY_PROXY.labels(mode=mode).observe(ratio)


def observe_ingest_e2e(*, input_type: str, duration_ms: float) -> None:
    INGEST_PIPELINE_E2E.labels(input_type=input_type).observe(duration_ms)


def observe_ingest_stage(*, stage: str, input_type: str, status: str, duration_ms: float) -> None:
    INGEST_STAGE_DURATION.labels(stage=stage, input_type=input_type, status=status).observe(duration_ms)


def observe_ingest_fetch_latency(*, input_type: str, content_type: str, duration_ms: float) -> None:
    INGEST_FETCH_LATENCY.labels(input_type=input_type, content_type=content_type).observe(duration_ms)


def observe_ingest_route_distribution(*, input_type: str, category: str) -> None:
    INGEST_ROUTE_DISTRIBUTION.labels(input_type=input_type, category=category).inc()


def observe_ingest_parse_success(*, input_type: str, parser: str, result: str) -> None:
    INGEST_PARSE_SUCCESS.labels(input_type=input_type, parser=parser, result=result).inc()


def observe_ingest_fallback_rate(*, input_type: str, trigger: str) -> None:
    INGEST_FALLBACK_RATE.labels(input_type=input_type, trigger=trigger).inc()


def observe_ingest_synthetic_toc(*, input_type: str, result: str) -> None:
    INGEST_SYNTHETIC_TOC.labels(input_type=input_type, result=result).inc()


def observe_ingest_block_completeness(*, input_type: str, block_type: str, count: int = 1) -> None:
    INGEST_BLOCK_COMPLETENESS.labels(input_type=input_type, block_type=block_type).inc(count)


def observe_summary_e2e(*, duration_ms: float) -> None:
    SUMMARY_PIPELINE_E2E.observe(duration_ms)


def observe_summary_stage(*, stage: str, status: str, duration_ms: float) -> None:
    SUMMARY_STAGE_DURATION.labels(stage=stage, status=status).observe(duration_ms)


def observe_summary_route_mix(*, route: str) -> None:
    SUMMARY_ROUTE_MIX.labels(route=route).inc()


def observe_summary_judge_reject(*, reason: str) -> None:
    SUMMARY_JUDGE_REJECT.labels(reason=reason).inc()


def observe_summary_fallback(*, trigger: str) -> None:
    SUMMARY_FALLBACK.labels(trigger=trigger).inc()


def observe_summary_cache_hit() -> None:
    SUMMARY_CACHE_HIT.inc()


def observe_chat_e2e(*, duration_ms: float) -> None:
    CHAT_PIPELINE_E2E.observe(duration_ms)


def observe_chat_stage(*, stage: str, route: str, status: str, duration_ms: float) -> None:
    CHAT_STAGE_DURATION.labels(stage=stage, route=route, status=status).observe(duration_ms)


def observe_chat_route_mix(*, route: str) -> None:
    CHAT_ROUTE_MIX.labels(route=route).inc()


def observe_chat_fallback(*, reason: str) -> None:
    CHAT_FALLBACK.labels(reason=reason).inc()


def observe_chat_evidence_coverage(*, route: str, coverage: float) -> None:
    CHAT_EVIDENCE_COVERAGE.labels(route=route).observe(coverage)


def observe_chat_retrieval(*, route: str, evidence_count: int, recommendation_count: int) -> None:
    CHAT_RETRIEVAL_EVIDENCE_COUNT.labels(route=route).observe(evidence_count)
    CHAT_RETRIEVAL_RECOMMENDATION_COUNT.labels(route=route).observe(recommendation_count)


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
    try:
        start_http_server(port, addr=addr)
    except OSError:
        import socket
        from wsgiref.simple_server import make_server, WSGIServer

        class _ReuseServer(WSGIServer):
            allow_reuse_address = True
            allow_reuse_port = True

            def server_bind(self):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                super().server_bind()

        from prometheus_client import make_wsgi_app, exposition
        app = make_wsgi_app()
        httpd = make_server(addr, port, app, _ReuseServer)
        import threading
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
    _STARTED_PORTS.add(key)


def render_metrics() -> bytes:
    return generate_latest()
