# =============== 观测总览 ===============

当前系统的观测体系只对三条核心业务链路做最高优先级保障：

1. Search
2. Import / Ingest
3. AI Generation

观测信号分成三层：

- Logging：用于故障排查和单次事件还原
- Metrics：用于趋势分析、性能分布和质量聚合
- Tracing：用于关键阶段耗时拆解和依赖定位

观测相关的业务封装已经统一收口到 `backend/app/modules/tracker/`，避免在 service 和 worker 里散落拼接指标与 span。

# =============== 在线观测架构 ===============

```text
API / Worker / Scheduler
  |- structured logs ---------------------> Loki
  |- prometheus metrics ------------------> Prometheus
  `- OpenTelemetry traces ----------------> OTel Collector -> Tempo

Grafana
  |- Prometheus
  |- Loki
  `- Tempo
```

代码落点：

- Logging：
  - `backend/app/infra/telemetry/logging.py`
  - `backend/app/api/middleware.py`
- Metrics：
  - `backend/app/infra/telemetry/metrics.py`
  - `backend/app/modules/tracker/*`
- Tracing：
  - `backend/app/infra/telemetry/tracing.py`

`tracker` 包的职责：

- 统一 stage timer
- 更新 counter / histogram / gauge
- 限制 label 维度，避免高基数
- 写入线上评审与巡检产物
- 在业务关键边界补手动 span

# =============== 低基数约束 ===============

当前代码已经把通用 HTTP 指标从原始 URL path 改成了路由模板 path。

例如：

- `/api/notebooks/123` -> `/api/notebooks/{notebook_id}`
- `/api/articles/456` -> `/api/articles/{article_id}`

这样做是为了避免 Prometheus 时序爆炸。当前明确不允许直接做成指标或 Loki labels 的字段包括：

- `query_text`
- `user_id`
- `doc_id`
- `article_id`
- `search_session_id`
- `conversation_id`
- `trace_id`

这些字段只允许进入日志正文、trace metadata、采样 JSONL 或 benchmark 报告，不进入高频 label。

# =============== 指标体系 ===============

## 通用入口指标

### HTTP

- `notebooklm_http_requests_total`
- `notebooklm_http_request_duration_ms`

作用：

- 看全局 API 流量、状态码和接口级耗时
- 只做入口观测，不替代核心业务指标

### MQ / Scheduler

- `notebooklm_mq_publish_total`
- `notebooklm_mq_publish_duration_ms`
- `notebooklm_scheduler_actions_total`

作用：

- 看消息发布是否卡顿
- 看 scheduler 的补偿、清理、巡检动作是否正常推进

## Search 指标

### 性能层

- `notebooklm_search_requests_total`
- `notebooklm_search_provider_duration_ms`
- `notebooklm_search_stage_duration_ms`
- `notebooklm_search_result_count`
- `notebooklm_source_import_total`

### 质量层

- `notebooklm_search_result_score`
  - `quality`
  - `recency`
  - `authority`
  - `credibility`
  - `professional`
- `notebooklm_search_result_signal_total`
  - `freshness_satisfied`
  - `authority_hit`

### 在线评审层

- `notebooklm_search_review_samples_total`
- `notebooklm_search_review_score`
- `notebooklm_search_review_bad_cases_total`

当前 Search 线上评审已经不是只有规则采样：

1. 先做规则评审
2. 按配置做可选 LLM judge
3. 坏例子回流到 JSONL

Search 评审输出目录：

- `backend/evals/reports/search_samples/`
- `backend/evals/reports/search_bad_cases/`

## Import / Ingest 指标

### 阶段耗时

- `notebooklm_ingest_parse_total`
- `notebooklm_ingest_fallback_total`
- `notebooklm_ingest_stage_duration_ms`
- `notebooklm_ingest_ready_duration_ms`
- `notebooklm_ingest_chunk_count`

### Markdown 质量

- `notebooklm_ingest_markdown_quality_score`
- `notebooklm_ingest_structure_score`
  - `title_hierarchy`
  - `list`
  - `table`
  - `image`
  - `link`

### 文档类型维度

- `notebooklm_ingest_doc_type_total`
- `notebooklm_ingest_doc_type_quality_score`
- `notebooklm_ingest_doc_type_structure_score`

当前文档类型观测已经能区分：

- `pdf`
- `pdf_scanned`
- `word`
- `powerpoint`
- `html`
- `markdown`
- `plain_text`
- `image`
- `webpage`
- `other_file`

这意味着现在可以直接回答：

- 哪种文档类型 parse 成功率低
- 哪种文档类型结构恢复差
- OCR 类文档和非 OCR 文档的质量差异

## AI 指标

### 性能层

- `notebooklm_ai_requests_total`
- `notebooklm_ai_request_duration_ms`
- `notebooklm_ai_first_token_ms`
- `notebooklm_ai_token_stream_duration_ms`
- `notebooklm_llm_calls_total`
- `notebooklm_llm_call_duration_ms`
- `notebooklm_llm_tokens_total`

### 路由与检索层

- `notebooklm_ai_route_total`
- `notebooklm_ai_retrieval_context_count`
- `notebooklm_ai_cache_lookup_total`
- `notebooklm_ai_answer_length_chars`

### 用户行为代理

- `notebooklm_ai_user_actions_total`
  - `follow_up`
  - `citation_open`
  - `answer_copy`
  - `summary_copy`

### 在线评审层

- `notebooklm_ai_online_review_total`
- `notebooklm_ai_online_review_score`
- `notebooklm_ai_online_review_bad_cases_total`

当前 AI 在线质量已经不只看行为代理。对抽样的 chat 和 summary 结果，会做 LLM judge，评审维度包括：

- `groundedness`
- `faithfulness`
- `completeness`
- `overall`

AI 评审输出目录：

- `backend/evals/reports/ai_reviews/`
- `backend/evals/reports/ai_bad_cases/`

## Redis 巡检指标

- `notebooklm_redis_inspection_runs_total`
- `notebooklm_redis_inspection_keys_scanned`
- `notebooklm_redis_bigkey_count`
- `notebooklm_redis_biggest_key_bytes`
- `notebooklm_redis_hotkey_count`
- `notebooklm_redis_hottest_key_frequency`
- `notebooklm_redis_inspection_last_success_unixtime`

巡检原始结果写入：

- `backend/evals/reports/redis/`

## 基础设施指标

### Redis

- `redis_commands_processed_total`
- `redis_keyspace_hits_total`
- `redis_keyspace_misses_total`
- `redis_evicted_keys_total`

### PostgreSQL

- `pg_stat_database_numbackends`
- `pg_stat_database_deadlocks`
- `pg_stat_database_xact_commit`
- `pg_stat_database_xact_rollback`
- `pg_locks_count`
- `pg_stat_database_blks_hit`
- `pg_stat_database_blks_read`

### 机器层

- `node_cpu_seconds_total`
- `node_memory_MemAvailable_bytes`
- `node_memory_MemTotal_bytes`
- `node_disk_read_bytes_total`
- `node_disk_written_bytes_total`
- `node_network_receive_bytes_total`
- `node_network_transmit_bytes_total`

这些指标的目标不是“全监控”，而是和 Search / Ingest / AI 的延迟和失败关联起来看。

# =============== Prometheus 与 Grafana ===============

Prometheus recording rules 位于：

- `docker/prometheus/notebooklm-rules.yml`

当前规则覆盖：

- Search：throughput、provider P95、stage P95、result count、质量分、采样评审分数和坏例子计数
- Ingest：parse 结果、stage P95、markdown 质量、structure 质量、per-doc-type 统计
- AI：request P95、TTFT、stream P95、route、cache、user action ratio、online review 分数和坏例子计数
- Infra：node、redis、postgres、redis inspection

当前只保留 recording rules，不再维护告警通知链路。

Grafana 当前主要面板：

- `search-dashboard.json`
- `ingest-dashboard.json`
- `llm-dashboard.json`
- `kafka-dashboard.json`
- `infra-dashboard.json`
- `benchmark-dashboard.json`

面板职责：

- `search-dashboard`
  - Search 吞吐、阶段耗时、质量分、采样评审
- `ingest-dashboard`
  - parse / ready / chunk / embed / structure / per-doc-type 质量
- `llm-dashboard`
  - chat / summary 延迟、TTFT、route、cache、行为代理、online review
- `infra-dashboard`
  - Redis、PostgreSQL、机器资源、Redis inspection
- `benchmark-dashboard`
  - 离线 benchmark textfile 指标趋势

# =============== benchmark 与 textfile 链路 ===============

离线 benchmark 产物目录：

- `backend/evals/cases/`
- `backend/evals/datasets/`
- `backend/evals/reports/predictions/`
- `backend/evals/reports/baselines/`
- `backend/evals/reports/prometheus/`

当前 benchmark runner 会输出：

- JSON 报告
- Markdown 报告
- baseline 对比
- Prometheus textfile

Prometheus textfile 的链路是：

```text
benchmark runner
  -> backend/evals/reports/prometheus/*.prom
  -> node-exporter textfile collector
  -> Prometheus
  -> Grafana benchmark dashboard
```

默认 profile 已经切到 `stable`，不再只依赖 demo 资产。

# =============== 当前输出物 ===============

当前线上和离线观测会落出以下文件类产物：

- Search 采样评审：
  - `backend/evals/reports/search_samples/*.jsonl`
  - `backend/evals/reports/search_bad_cases/*.jsonl`
- AI 在线评审：
  - `backend/evals/reports/ai_reviews/*.jsonl`
  - `backend/evals/reports/ai_bad_cases/*.jsonl`
- Redis 巡检：
  - `backend/evals/reports/redis/*.json`
- Benchmark 报告：
  - `backend/evals/reports/*.json`
  - `backend/evals/reports/*.md`
  - `backend/evals/reports/prometheus/*.prom`

这些文件分别承担：

- 线上坏例子回流
- 人工复盘
- benchmark 历史留档
- Grafana 离线趋势展示







目前项目的完成度基本能通过baseline，我想从下面五个方面切入做改进。请你分别进行调研业界的成熟方案，然后在 docs目录下创建ADR文档。

1. 搜索链路：我的目标是提高检索的质量，不考虑对模型层做改进，只考虑工程。我的预想是
2. 解析链路：
3. summary链路
4. 性能链路：redis缓存，
5. 稳定性链路：postgre..... redis缓存一致性..... kafka失败幂等...... 安全性sql xss 加密......
