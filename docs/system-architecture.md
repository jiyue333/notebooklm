# NotebookLM 系统架构

## 项目定位

NotebookLM 是一个 AI 研究助手，帮助用户搜索、导入、阅读、摘要和讨论文档。核心链路四条：Search → Ingest → Summary → Chat。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 19 + Vite 7 + react-router-dom 7 |
| 后端 | FastAPI + Python 3.12 |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis |
| 消息队列 | Kafka（通过 aiokafka） |
| 对象存储 | MinIO（S3 兼容） |
| AI / LLM | LangChain + OpenAI / Ollama |
| 向量化 | OpenAI Embeddings / Ollama |
| 搜索 API | Exa |
| 可观测性 | Prometheus + Grafana + Loki + Tempo + OpenTelemetry |

## 整体架构

```
┌──────────────┐       ┌────────────────────────────────────────┐
│   Frontend   │──────▶│              FastAPI (API)              │
│  React SPA   │◀──SSE─│  main.py → routers → services          │
└──────────────┘       └──────────┬─────────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
             ┌───────────┐ ┌───────────┐ ┌───────────┐
             │ PostgreSQL │ │   Redis   │ │   MinIO   │
             │ + pgvector │ │  (cache)  │ │  (files)  │
             └───────────┘ └───────────┘ └───────────┘
                    ▲
                    │
              ┌─────┴──────┐
              │   Worker    │◀── Kafka ◀── Job Publisher
              │ (article    │
              │  ingest)    │
              └─────────────┘
```

## 后端模块结构

```
backend/app/
├── api/                  # HTTP 层：中间件、依赖注入、错误处理、SSE
├── core/                 # 配置（pydantic-settings）
├── infra/                # 基础设施（不含业务逻辑）
│   ├── ai/               #   LLM chat_models + Embedder
│   ├── cache/            #   Redis 客户端 + cache service
│   ├── db/               #   SQLAlchemy base + session + model registry
│   ├── mq/               #   Kafka producer / consumer
│   ├── providers/exa/    #   Exa Search + Contents 客户端
│   ├── security/         #   加密、密码、session token
│   ├── storage/          #   文件存储（本地 / MinIO）
│   └── telemetry/        #   logging, metrics, tracing, context
├── modules/              # 业务模块
│   ├── search/           #   搜索链路（ADR-001）
│   ├── ingest/           #   解析链路（ADR-002）
│   ├── ai/summary/       #   摘要链路（ADR-003）
│   ├── ai/chat/          #   聊天链路（ADR-004）
│   ├── auth/             #   用户认证
│   ├── notebooks/        #   笔记本 + 文章 CRUD
│   ├── notes/            #   笔记 CRUD
│   ├── jobs/             #   异步任务（Job 表 + Kafka 发布）
│   └── settings/         #   用户设置 + 运行时配置
└── workers/              # 后台进程
    ├── run_worker.py     #   Kafka 消费者（处理 article_ingest）
    └── run_scheduler.py  #   定时任务（缓存清理、Job 重发）
```

## 四条核心链路

### 1. Search（ADR-001）

用户输入查询 → 多阶段流水线 → 返回候选文章列表。

```
用户 query + notebook context
    → A: Task Parsing（规则化理解意图）
    → B: Query Lattice（生成 2-7 个查询家族）
    → C: Multi-Source Recall（并发调用 Exa API）
    → D: Canonicalize（URL/DOI 去重）
    → E: Enrichment（推断 doc_type / authority）
    → F: Multi-Objective Scoring（8 维加权打分）
    → G: Slate Building（按 bucket 覆盖式选取 + why_selected）
    → 持久化 SearchSession + SearchResult
```

路径：`modules/search/pipeline/`，对外入口 `sessions/service.py`。
同步执行，p95 约 3-4 秒。

### 2. Ingest（ADR-002）

用户导入文章 → 立即创建 Article（queued）→ 异步 Job 执行解析。

```
Article 创建（router）
    → Job 发布到 Kafka（或 inline fallback）
    → Worker 消费 Job：
        → A: Fetch（下载 URL / 读取文件）
        → B: Canonicalize（去重）
        → C: Doc Router（分类：html/pdf/office/text）
        → D: Multi-Parser（Trafilatura + Exa + MarkItDown）
        → E: Quality Judge（8 维解析质量打分）
        → F: Fusion（合并最优候选 + markdown 清理）
        → G: TOC Builder（heading 提取 / synthetic TOC）
        → H: BlockGraph（结构化 block AST）
        → I: Indexer（分块 + 向量化）
    → 更新 Article（clean_markdown, toc, block_graph, chunks）
```

路径：`modules/ingest/pipeline/`，Worker 入口 `workers/handlers/__init__.py`。
Article 的 `block_graph_json` 和 `quality_profile_json` 持久化到 DB，供 Summary / Chat 跨请求消费。

### 3. Summary（ADR-003）

用户点击文章摘要按钮 → SSE 流式返回。

```
Article 内容（从 DB 读取）
    → A: Article Profiling（识别类型/证据风格/结构质量）
    → B: Evidence Extraction（按 section role 权重提取 8-12 个 bullets）
    → C: Route Selection（S/M/L/X 四档，低质量走保守路由）
    → D: Candidate Generation + Judge（3 种风格候选 + 四维评审）
    → E: Final Output（ArticleSummary + evidence_spans）
    → 缓存到 SummaryCache 表
```

路径：`modules/ai/summary/pipeline/`，SSE 入口 `ai/router.py`。
缓存命中时直接返回；首次生成走完整 pipeline。

### 4. Chat（ADR-004）

用户在文章内提问 → SSE 流式返回。

```
用户问题 + article_id + notebook_id
    → A: Scope Router（四路由分类）
        article_grounded / general / recommendation / notebook_research
    → B: Route-Specific Retrieval
        - article_grounded: 当前文章 chunk 检索
        - general: 不检索
        - recommendation: article-level 检索
        - notebook_research: 两阶段（article shortlist → section evidence）
    → C: Answer Composer（按路由协议生成回答）
    → D: Verifier（证据覆盖率 + scope 一致性 + fallback）
    → 持久化 Conversation + ConversationMessage
```

路径：`modules/ai/chat/pipeline/`，SSE 入口 `ai/router.py`。
每条 lane 有独立回答协议和 route badge（`From this article` / `General answer` / `From your notebooks` / `Research in this notebook`）。

## 数据模型

```
users ──< notebooks ──< articles ──< article_chunks
                    ──< notes
                    ──< search_sessions ──< search_results
          conversations ──< conversation_messages
          summary_caches
          jobs
```

核心表：

| 表 | 作用 | 关键字段 |
|----|------|---------|
| `articles` | 文章（ingest 产物） | clean_markdown, toc_json, block_graph_json, quality_profile_json, parse_status |
| `article_chunks` | 文章分块（向量检索用） | chunk_text, chunk_vector (pgvector) |
| `search_sessions` | 搜索会话 | query, mode, status, result_count |
| `search_results` | 搜索结果卡片 | title, url, why_selected, display_rank |
| `summary_caches` | 摘要缓存 | article_id, content_hash, prompt_version, summary_text |
| `conversations` | 聊天会话 | notebook_id, current_article_id |
| `conversation_messages` | 聊天消息 | role, route, content, retrieval_snapshot_json |
| `jobs` | 异步任务 | job_type, article_id, status, payload_json |

## 可观测性

### 三支柱

| 支柱 | 工具 | 数据源 |
|------|------|--------|
| Metrics | Prometheus → Grafana | FastAPI metrics server（:8081 / :9101 / :9102） |
| Logs | structlog → Promtail → Loki → Grafana | JSON 单行日志，exception 扁平化 |
| Traces | OpenTelemetry → Tempo → Grafana | 分布式追踪，trace_id / span_id 注入日志 |

### Prometheus 指标体系

每条链路有独立的 Observer（`pipeline/observer.py`），通过注入模式与业务代码解耦：

- **Search**: e2e 延迟、阶段延迟、去重命中率、空 slate 率、authority/diversity/novelty@10
- **Ingest**: e2e 延迟、fetch 延迟、parser 路由分布、解析成功率、fallback 率、TOC 合成率、block 完整度
- **Summary**: e2e 延迟、阶段延迟、路由分布(S/M/L/X)、judge 拒绝率、fallback 率、缓存命中率
- **Infra**: HTTP 请求延迟、scheduler 动作计数、MQ 发布/消费

### Grafana Dashboard

| Dashboard | 覆盖 |
|-----------|------|
| search-dashboard.json | Search 链路指标 |
| ingest-dashboard.json | Ingest 链路指标 |
| summary-dashboard.json | Summary 链路指标 |
| chat-dashboard.json | Chat 链路指标 |
| infra-dashboard.json | HTTP / Redis / Postgres / MQ |
| kafka-dashboard.json | Kafka broker 指标 |

## 异步任务

当前仅 `article_ingest` 一种 Job 类型走异步：

```
Router 创建 Article(queued) + Job
    → publisher.publish_jobs → Kafka
    → Worker 消费 → process_article_ingest → ingest pipeline
    → 更新 Article 状态
```

Kafka 不可用时自动走 inline fallback（在 API 进程内同步执行）。
Scheduler 每 15 秒执行一次，负责重发 pending Job、清理过期缓存和失败 Job。

## 进程模型

| 进程 | 入口 | 职责 |
|------|------|------|
| API | `uvicorn app.main:app` | HTTP 请求处理 |
| Worker | `python -m app.workers.run_worker` | Kafka 消费，执行 ingest Job |
| Scheduler | `python -m app.workers.run_scheduler` | 定时清理任务 |

`scripts/dev.sh` 负责启动/停止/重启这三个进程。

## 前端架构

React SPA，核心页面：

| 页面 | 文件 | 功能 |
|------|------|------|
| 首页 | `HomePage.jsx` | 笔记本列表 |
| 笔记本 | `NotebookPage.jsx` | 文章列表、搜索、阅读、摘要、聊天 |
| 登录 | `LoginPage.jsx` | 用户认证 |

API 通信通过 `services/appApi.js`，SSE 流式接口用于摘要和聊天。

## ADR 索引

| ADR | 链路 | 状态 |
|-----|------|------|
| [ADR-001](adr/ADR-001-search-retrieval-quality-pipeline.md) | Search | 已实现 |
| [ADR-002](adr/ADR-002-parse-pipeline-and-quality-evaluation.md) | Ingest | 已实现 |
| [ADR-003](adr/ADR-003-summary-pipeline-and-quality-evaluation.md) | Summary | 已实现 |
| [ADR-004](adr/ADR-004-chat-pipeline.md) | Chat | 已实现 |
| [ADR-005](adr/ADR-005-mainline-performance-optimization.md) | 性能优化 | Proposal |
| [ADR-006](adr/ADR-006-stability-security-hardening.md) | 稳定性/安全 | Proposal |
