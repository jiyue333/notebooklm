from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.constant import (
    PROVIDER_EXA,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
)

BASE_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "NotebookLM Backend"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"
    host: str = "127.0.0.1"
    port: int = 8080
    secret_key: str = "change-me"
    auth_token_ttl_days: int = 30

    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/notebooklm"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20

    redis_url: str = "redis://127.0.0.1:6379/0"
    redis_decode_responses: bool = False
    redis_cache_enabled: bool = True
    cache_ttl_notebook_detail_seconds: int = 30
    cache_ttl_notebook_detail_pending_seconds: int = 2
    cache_ttl_search_session_completed_seconds: int = 300
    cache_ttl_search_session_pending_seconds: int = 2
    cache_ttl_settings_seconds: int = 900
    redis_inspection_enabled: bool = True
    redis_inspection_interval_seconds: int = 900
    redis_inspection_sample_limit: int = 200
    redis_inspection_scan_count: int = 50
    redis_bigkey_threshold_bytes: int = 262144
    redis_hotkey_frequency_threshold: int = 32
    redis_inspection_top_n: int = 10

    exa_base_url: str = "https://api.exa.ai"
    exa_default_api_key: str | None = None
    tavily_base_url: str = "https://api.tavily.com"
    tavily_default_api_key: str | None = None
    search_inline_deadline_ms: int = 4500
    search_review_sampling_enabled: bool = True
    search_review_sampling_rate: float = 0.02
    search_review_sampling_mode: str = "rule_llm"
    search_review_bad_case_threshold: float = 0.55

    ai_review_sampling_enabled: bool = True
    ai_review_sampling_rate: float = 0.02
    ai_review_sampling_mode: str = "llm"
    ai_review_bad_case_threshold: float = 0.6

    default_chat_api_key: str | None = None
    embedding_default_api_key: str | None = None
    default_chat_provider: str = PROVIDER_OLLAMA
    default_chat_model_name: str = "qwen3.5:0.8b"
    default_chat_api_url: str = "http://127.0.0.1:11434"
    default_search_provider: str = PROVIDER_EXA
    default_embedding_provider: str = PROVIDER_OLLAMA
    default_embedding_model_name: str = "qwen3-embedding:0.6b"
    default_embedding_api_url: str = "http://127.0.0.1:11434"
    embedding_output_dimensions: int = 1024
    chunk_target_tokens: int = 600
    chunk_overlap_tokens: int = 80
    summary_cache_ttl_days: int = 30
    scheduler_failed_job_retention_days: int = 14

    grok_api_key: str | None = None
    grok_base_url: str = "https://api.x.ai/v1"
    grok_model: str = "grok-3-mini-beta"

    lite_llm_provider: str = PROVIDER_OPENAI
    lite_llm_api_key: str | None = None
    lite_llm_base_url: str = "https://a-ocnfniawgw.cn-shanghai.fcapp.run"
    lite_llm_model: str = "claude-haiku-4-5-20251001"
    lite_llm_timeout: int = 60  # scoring 15 items can be slow; increase if score_fallback occurs

    rerank_model: str = "Qwen3-Reranker-8B"
    rerank_model_api_url: str = "https://router.tumuer.me/v1"
    rerank_model_api_key: str | None = None
    rerank_timeout: int = 30
    rerank_max_concurrency: int = 5

    search_use_llm_task_parser: bool = False

    # ── Summary pipeline ───────────────────────────────────────────
    summary_map_reduce_threshold_tokens: int = 8000
    summary_max_retries: int = 2
    summary_compress_code_blocks: bool = True

    # ── Chat retrieval ─────────────────────────────────────────────
    chat_dense_top_k: int = 15
    chat_sparse_top_k: int = 15
    chat_rerank_top_n: int = 8
    chat_dense_weight: float = 0.7
    chat_sparse_weight: float = 0.3
    chat_web_search_score_threshold: float = 0.3

    # ── Ingest document parsing ────────────────────────────────────
    # Tika
    tika_server_url: str = ""

    # MinerU Cloud API
    mineru_api_token: str = ""
    mineru_api_base_url: str = "https://mineru.net/api/v4"
    mineru_default_model: str = "vlm"
    mineru_poll_interval_seconds: int = 3
    mineru_poll_timeout_seconds: int = 300

    # Remark (Node.js subprocess)
    remark_processor_path: str = ""
    remark_timeout_seconds: int = 30

    kafka_bootstrap_servers: str = "127.0.0.1:29092"
    kafka_topic: str = "notebook_async"
    kafka_consumer_poll_timeout_ms: int = 1000
    kafka_request_timeout_ms: int = 10000
    kafka_session_timeout_ms: int = 30_000  # 30s, heartbeat; handler 的 sync 会阻塞 event loop
    kafka_max_poll_interval_ms: int = 600_000  # 10 min, allow long ingest/embed
    kafka_auto_offset_reset: str = "earliest"

    object_storage_endpoint: str = "127.0.0.1:9000"
    object_storage_access_key: str = "minioadmin"
    object_storage_secret_key: str = "minioadmin"
    object_storage_bucket: str = "notebooklm"
    object_storage_secure: bool = False
    object_storage_region: str | None = None
    file_storage_backend: str = "minio"

    log_level: str = "INFO"
    log_json: bool = True
    log_file: str | None = None  # 设置后同时写入文件，供 Promtail 采集到 Loki
    api_metrics_port: int = 8080
    worker_metrics_port: int = 9101
    scheduler_metrics_port: int = 9102

    otel_enabled: bool = True
    otel_service_name: str = "notebooklm-backend"
    otel_exporter_otlp_endpoint: str | None = None

    langsmith_enabled: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_project: str = "notebooklm-backend"
    langsmith_workspace_id: str | None = None
    langsmith_tracing: bool = False

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
        ]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            return value
        if not value:
            return []
        parsed = value.strip()
        if parsed.startswith("[") and parsed.endswith("]"):
            parsed = parsed[1:-1]
        return [item.strip().strip("\"'") for item in parsed.split(",") if item.strip()]

    @property
    def database_url_sync(self) -> str:
        if "+asyncpg" in self.database_url:
            return self.database_url.replace("+asyncpg", "+psycopg", 1)
        return self.database_url

    @property
    def search_review_output_dir(self) -> Path:
        return BASE_DIR / "evals" / "reports" / "search_samples"

    @property
    def search_review_bad_case_output_dir(self) -> Path:
        return BASE_DIR / "evals" / "reports" / "search_bad_cases"

    @property
    def ai_review_output_dir(self) -> Path:
        return BASE_DIR / "evals" / "reports" / "ai_reviews"

    @property
    def ai_review_bad_case_output_dir(self) -> Path:
        return BASE_DIR / "evals" / "reports" / "ai_bad_cases"

    @property
    def redis_inspection_output_dir(self) -> Path:
        return BASE_DIR / "evals" / "reports" / "redis"


@lru_cache
def get_settings() -> Settings:
    return Settings()
