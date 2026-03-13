# =============== 系统总览 ===============

NotebookLM 当前是一个单仓库、单前端、三运行单元的系统：

- `frontend/`：React + Vite 单页应用
- `backend/app/main.py`：FastAPI API
- `backend/app/workers/run_worker.py`：异步 worker
- `backend/app/workers/run_scheduler.py`：周期调度器

系统围绕三条核心业务链路组织：

1. 搜索：发现候选来源并生成搜索会话
2. 导入：把来源变成 notebook 内可读、可检索的 article
3. AI：基于 article 和 notebook 内容完成 summary 与 chat

当前所有正式结构文档以本文件为准。这里不描述未来规划，只描述当前仓库已经存在的系统结构。

# =============== 运行时组件 ===============

## 客户端

- `frontend/src/`
- 负责登录、notebook 工作台、搜索与导入、文章阅读、摘要、对话、设置
- 通过 `frontend/src/services/appApi.js` 调用 `/api/*`
- `chat` 和 `summary` 的流式接口通过 SSE 使用

## API

- 入口：`backend/app/main.py`
- 路由：
  - `auth`
  - `notebooks`
  - `notes`
  - `search`
  - `ai`
  - `settings`
  - `health`
- 负责同步请求编排、DB 读写、短链路搜索、inline ingest、SSE 输出、缓存读取、异步任务发布

## Worker

- 入口：`backend/app/workers/run_worker.py`
- 当前消费的 job 类型：
  - `search_deep`
  - `article_ingest`
  - `article_reindex`
- 负责深度搜索、网页抓取、解析清洗、chunking、embedding、索引重建

## Scheduler

- 入口：`backend/app/workers/run_scheduler.py`
- 负责：
  - 重发未发布或待补偿 job
  - 过期 search session 清理
  - summary cache 清理
  - 历史失败 job 清理
  - Redis bigkey / hotkey 巡检触发

## 数据与基础设施

- PostgreSQL + pgvector：主数据、全文检索、向量检索
- Redis：读缓存与巡检对象
- MinIO：文件与图片对象存储
- Kafka：异步任务传输
- Exa：搜索与网页正文抓取
- Ollama / OpenAI-compatible：chat、summary、embedding

## 观测组件

- Prometheus
- Grafana
- Loki
- Tempo
- OTel Collector
- `kafka-exporter`
- `redis-exporter`
- `postgres-exporter`
- `node-exporter`

# =============== 核心业务链路 ===============

## Search

关键代码：

- `backend/app/modules/search/router.py`
- `backend/app/modules/search/sessions/service.py`
- `backend/app/modules/search/sources/manual_service.py`
- `backend/app/modules/search/sources/import_service.py`

当前结构：

1. 前端发起 `sources/search`
2. API 创建 `search_session`
3. 快速模式尝试 inline 搜索，超时或 deep 模式则创建 `search_deep` job
4. 搜索结果写入 `search_results`
5. 前端用 `searchSessionId + searchResultIds` 发起 `sources/import`

Search 只负责发现候选来源，不负责 chunking 和 embedding。

## Import / Ingest

关键代码：

- `backend/app/modules/ingest/articles/service.py`
- `backend/app/modules/ingest/articles/worker.py`
- `backend/app/modules/ingest/indexing/pipeline.py`
- `backend/app/modules/ingest/quality/quality_scorer.py`

来源入口：

- 搜索结果导入
- 手动 text
- 手动 url
- 文件上传
- 剪贴板图片

当前结构：

1. 所有来源先统一成 `IngestDraft`
2. 若能 inline 解析，则直接生成 `clean_markdown`
3. 若需要异步抓取或解析，则创建 `article_ingest` job
4. `parse_status=ready` 代表正文可读
5. chunking、embedding、索引状态与正文 ready 解耦

## AI

关键代码：

- `backend/app/modules/ai/chat/*`
- `backend/app/modules/ai/summary/*`
- `backend/app/modules/retrieval/*`

当前结构：

- Summary：
  - 输入是 article 的 `clean_markdown`
  - 命中 `summary_cache` 时直接返回
  - 未命中时调用模型生成并写回缓存
- Chat：
  - 会话和消息保存在数据库
  - 路由器先判断是否需要当前文章、相关资料或证据检索
  - 检索分 article 级和 chunk 级
  - 支持普通返回与 SSE 流式返回

# =============== 数据与状态 ===============

## 主要业务实体

- `User`
- `Notebook`
- `Article`
- `ArticleChunk`
- `Note`
- `SearchSession`
- `SearchResult`
- `Job`
- `Conversation`
- `ConversationMessage`
- `SummaryCache`

## 关键状态字段

### Article

- `parse_status`
  - `pending`：正文还未准备好
  - `ready`：正文可读
  - `failed`：解析失败
- `chunk_status`
  - 反映 chunk 是否已完成
- `index_status`
  - 反映全文 / 向量索引是否就绪
- `embedding_status`
  - 反映 embedding 计算是否成功

### SearchSession

- `queued`
- `running`
- `completed`
- `failed`
- `expired`

### Job

- `pending`
- `published`
- `running`
- `succeeded`
- `failed`
- `dead`

## 当前代码组织

### 业务模块

- `backend/app/modules/auth`
- `backend/app/modules/settings`
- `backend/app/modules/notebooks`
- `backend/app/modules/notes`
- `backend/app/modules/search`
- `backend/app/modules/ingest`
- `backend/app/modules/retrieval`
- `backend/app/modules/ai`
- `backend/app/modules/jobs`
- `backend/app/modules/tracker`

### 基础设施模块

- `backend/app/infra/db`
- `backend/app/infra/cache`
- `backend/app/infra/storage`
- `backend/app/infra/mq`
- `backend/app/infra/ai`
- `backend/app/infra/providers`
- `backend/app/infra/telemetry`

当前代码已经把基础设施能力尽量下沉到 `infra/`，并把观测与质量评审收口到 `tracker/`。

# =============== 异步与观测 ===============

## 异步结构

API 不直接以 Kafka 为真相源，异步任务遵循两层结构：

1. `jobs` 表记录状态真相
2. Kafka 负责运输 job payload

当前异步职责：

- API：写 `jobs` 行并发布消息
- Worker：消费消息并推进 `jobs` 与业务状态
- Scheduler：补偿、重发、清理

## 在线观测结构

### Logs

- API / worker / scheduler 输出结构化日志
- 本地日志文件位于 `logs/`
- Promtail 采集到 Loki

### Metrics

- 应用自定义指标在 `backend/app/infra/telemetry/metrics.py`
- Search / Ingest / AI 的业务埋点集中由 `backend/app/modules/tracker/*` 驱动
- Prometheus 抓取：
  - API / worker / scheduler
  - Kafka exporter
  - Redis exporter
  - PostgreSQL exporter
  - Node exporter

### Tracing

- OpenTelemetry 自动接入 FastAPI 和 SQLAlchemy
- 核心业务阶段额外补了手动 span
- trace 通过 OTel Collector 进入 Tempo

## 当前观测看板

- `docker/grafana/dashboards/search-dashboard.json`
- `docker/grafana/dashboards/ingest-dashboard.json`
- `docker/grafana/dashboards/llm-dashboard.json`
- `docker/grafana/dashboards/kafka-dashboard.json`
- `docker/grafana/dashboards/infra-dashboard.json`
- `docker/grafana/dashboards/benchmark-dashboard.json`

## 离线评测资产

离线评测代码保留在 `backend/evals/`：

- `cases/`
- `datasets/`
- `reports/`
- `dataset_builders/`
- `runners/`
- `online_seed/`
- `k6/`

这里负责 demo 数据、基线报告、离线 benchmark、在线造数与压测脚本，不承担主文档入口职责。
