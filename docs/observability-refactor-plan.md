# NotebookLM 可观测体系重构计划

## 1. 目标与核心边界

本次重构只把最高优先级放在 3 条核心业务链路：

1. 搜索
2. 导入
3. AI 生成内容

这 3 条链路需要做到：

- 在线可观测：能看延迟、吞吐、错误、质量代理指标、依赖耗时、业务趋势
- 离线可评估：能做 benchmark、回归、压测、质量基线
- 快速定位：日志、指标、trace 各自职责清晰，串起来能定位问题

本轮暂时降级优先级的内容：

- 笔记本 CRUD、笔记 CRUD、账号资料等非核心业务
- 泛化到所有接口的“全量指标”
- 过早引入过重的平台型组件
- 日志 TopN 聚合、1 分钟 ERROR 趋势、复杂日志分析面板


## 2. 当前现状分析

### 2.1 在线体系现状

当前项目已经有一套基础可观测链路，但偏“技术基线”，还没有围绕核心业务建立完整 SLI/SLO 和质量观测。

#### 2.1.1 Logging

现有能力：

- `structlog` JSON 日志，入口在 `backend/app/infra/telemetry/logging.py`
- 请求中间件会绑定 `request_id`、`http_method`、`http_path`，并记录 `request.completed`
- 当前 span 上下文会注入 `trace_id` / `span_id`
- `backend.log` / `worker.log` / `scheduler.log` / `frontend.log` 由 Promtail 推送到 Loki

现有问题：

- 业务事件没有形成统一 taxonomy，搜索、导入、AI 生成的事件模型不一致
- 没有“error signature”归一化，无法稳定做 1 分钟趋势和 TopN 异常聚类
- 业务质量相关日志几乎没有结构化字段，例如搜索质量评分、Markdown 质量、AI 回答质量代理指标
- 当前更偏故障排查，不足以支持运营型趋势分析

当前阶段结论：

- 日志必须继续保留并增强
- 但日志 TopN / 趋势分析这条线可以暂时放弃
- 当前日志主要职责仍然是故障排查和单次业务过程还原

#### 2.1.2 Metrics

现有能力：

- 使用 `prometheus_client` 手工埋点，入口在 `backend/app/infra/telemetry/metrics.py`
- 已有 HTTP、search、ingest、LLM、scheduler、MQ 等基础 counter / histogram
- Prometheus 已抓取 API / worker / scheduler / kafka-exporter
- Grafana 已经有 `search-dashboard.json`、`ingest-dashboard.json`、`llm-dashboard.json`、`kafka-dashboard.json`

现有问题：

- Search 只有请求量和 provider duration，没有完整业务阶段拆分
- Search 没有质量维度：命中多少、导入多少、来源实时性/可信度/专业性评分都没有
- Ingest 没有端到端耗时体系，只能看到局部 `ready` / `chunk` / `fallback`
- AI 没有首 token 时间、追问率、改写问题率、复制率等质量代理指标
- 基础设施指标不完整：缺 Redis、PostgreSQL、机器资源的 exporter 接入
- 还没有围绕核心业务定义告警阈值

#### 2.1.3 Tracing

现有能力：

- OpenTelemetry tracing 已接入 FastAPI 和 SQLAlchemy，入口在 `backend/app/infra/telemetry/tracing.py`
- OTLP traces 通过 OTel Collector 进入 Tempo
- 日志和 trace 已能通过 `trace_id` 关联

现有问题：

- 目前 trace 更偏框架级和 DB 级，业务 span 不足
- Search / Import / AI 的关键阶段没有完整 span 树
- Exa 检索、内容抓取、Markdown 清洗、chunking、embedding、chat route、prompt 组装、首 token 等关键节点没有系统化 trace 设计
- 目前还没有 Tempo metrics generator / service graph 的利用规划

当前部署约束下的判断：

- 项目当前是单机部署
- tracing 的核心价值不是跨服务拓扑，而是手动业务 span 的阶段耗时拆解
- 因此 trace 改造应优先补手动 span，而不是继续依赖自动 instrumentation 的默认粒度

#### 2.1.4 Dashboard / Alert

现有能力：

- Grafana + Prometheus + Loki + Tempo 基础联通
- 已有少量 dashboard

现有问题：

- dashboard 还是按技术模块切，不是按核心业务链路切
- 缺 Search / Import / AI 的业务总览页
- 缺“线上质量面板”，只能看耗时，不能看效果


### 2.2 离线体系现状

当前几乎没有成型的离线评估体系。

现状判断：

- 没有统一 benchmark 数据集目录
- 没有搜索召回 / 排序评估脚本
- 没有 RAG 问答评估脚本
- 没有摘要质量评估脚本
- 没有 API 压测脚本
- 没有基线版本、阈值、报告产物、回归对比

结论：

- 在线体系是“有基础设施，有少量埋点，但缺完整业务指标体系”
- 离线体系基本需要从 0 到 1 建


## 3. 重构原则

### 3.1 信号职责划分

#### Logging

Logging 负责：

- 事件触发记录
- 故障排查
- 异常调试
- 用文本检索还原某次业务过程

Logging 不负责：

- 长期趋势分析主视图
- 复杂统计计算
- 基准评测报告
- 1 分钟 ERROR 聚合 TopN 分析（当前阶段放弃）

#### Metrics

Metrics 负责：

- 业务趋势
- 性能指标
- 质量代理指标
- 阈值告警
- 热力图 / 仪表盘 / TopN / 分布统计
- 离线 benchmark 结果沉淀与可视化

Metrics 不负责：

- 还原单次请求的完整上下文
- 存放高基数原始文本

#### Tracing

Tracing 负责：

- 性能瓶颈定位
- 依赖分析
- 单次请求的延迟分解
- 故障链路定位
- 服务拓扑、阶段时序
- 手动业务 span 拆解函数耗时

Tracing 不负责：

- 聚合质量统计
- 长期业务报表


### 3.2 业务优先级

最高优先级：

- Search
- Import / Ingest
- AI Generation

第二优先级：

- Redis / PostgreSQL / Kafka / 机器资源

后续优先级：

- 非核心业务接口补齐
- 更复杂的平台化治理


## 4. 目标在线体系

### 4.1 总体架构

```text
Application
  |- structured logging (business events for troubleshooting)
  |- prometheus metrics (business SLI/SLO + infra)
  `- OpenTelemetry traces (manual business spans + dependency spans)

Logs
  Application -> Loki -> Grafana

Metrics
  Application metrics -> Prometheus
  Node / Redis / PostgreSQL / Kafka exporters -> Prometheus
  Offline benchmark summary -> Pushgateway or batch write -> Prometheus

Traces
  Application -> OTel Collector -> Tempo -> Grafana

Dashboards
  Grafana
    |- Search Business
    |- Import / Ingest Business
    |- AI Generation Business
    |- Infra Overview
    `- Offline Benchmarks
```


### 4.2 组件选择

保留并强化：

- OpenTelemetry Python SDK + OTel Collector
- Prometheus
- Grafana
- Loki
- Tempo
- `prometheus_client` 自定义业务指标
- LangSmith

新增：

- `node_exporter`：机器 CPU / Load / Mem / Disk / Network
- `redis_exporter`：Redis ops / command latency / connected clients / memory
- `postgres_exporter`：PostgreSQL connections / locks / cache hit / slow query proxy
- `k6`：API 压测与阈值门禁
- `Ragas`：RAG / QA 离线质量评估
- `rouge-score` + `bert-score`：摘要离线质量评估
- 在线数据创建脚本
- 离线数据集构造脚本
- benchmark 运行脚本

暂缓：

- 全量切 OTel Metrics
- MLflow / Weights & Biases 这类更重的离线实验平台
- Mimir 这类额外 metrics backend
- Grafana Alloy 替换 Promtail


### 4.3 为什么这样选

1. 当前代码已经基于 `prometheus_client` 埋点，短期继续沿用，风险最低。
2. tracing 已经是 OTel -> Collector -> Tempo，最合理的做法是补业务 span，而不是重做链路。
3. 日志目前是 structlog JSON + Loki，当前阶段继续保持即可，不值得为了单机部署先迁移采集组件。
4. 离线评估不需要第一天就上实验平台，先有统一数据集、脚本、阈值和报告更重要。
5. 这是一个单项目，不需要一开始就引入过多平台复杂度。
6. LangSmith 已经适合作为 LLM 侧在线观测和评估中台，不建议被 Ragas 替换。


### 4.4 LangSmith 与 Ragas 的职责判断

结论：

- 不切换掉 LangSmith
- 保留 LangSmith 做 AI 在线观测与在线/离线评估中台
- 引入 Ragas 只做离线 RAG benchmark，不替代 LangSmith

原因：

#### LangSmith 更适合做什么

- LLM / RAG trace 观测
- prompt / run / thread 调试
- 在线 evaluation
- 离线 dataset + experiment 对比
- 人工反馈与 judge 结果沉淀

#### Ragas 更适合做什么

- 离线 RAG 评估
- context precision / context recall / faithfulness / answer relevancy
- testset generation
- benchmark runner

#### 为什么不建议切换到 Ragas

1. Ragas 不是完整的在线 observability 平台。
2. 你当前已经有 LangSmith，直接切换会损失已有 trace 和在线评估能力。
3. Ragas 在这个项目里最合适的角色是离线 benchmark 引擎，而不是在线观测平台。

建议组合：

- 在线：Prometheus + Grafana + Loki + Tempo + LangSmith
- 离线：Ragas + rouge-score + bert-score + k6


## 5. 指标体系设计

### 5.1 Search 指标

#### 5.1.1 在线性能

必须建立：

- `search_request_total`
- `search_request_duration_ms`
- `search_stage_duration_ms{stage=provider_search|result_map|result_persist|response_build}`
- `search_result_count`
- `search_import_count`
- `search_import_rate`

建议按维度拆分：

- `mode`
- `execution`
- `provider`
- `status`

#### 5.1.2 在线质量代理指标

需要新增：

- `search_result_quality_score`
- `search_result_recency_score`
- `search_result_authority_score`
- `search_result_credibility_score`
- `search_result_professional_score`
- `search_result_freshness_satisfaction_rate`
- `search_result_authority_hit_rate`

建议解释：

- 实时性：依据 `published_at` 与当前时间的距离分桶
- 可信度：依据域名、HTTPS、作者、来源站点白名单/黑名单、结构化元数据完整度
- 专业性：依据标题/摘要风格、作者/机构标记、领域站点特征
- 综合质量分：上述几个 score 的加权结果
- 新鲜度满足率：结果是否满足该 query 的时效性要求
- 权威来源命中率：结果是否覆盖明确要求的权威来源

注意：

- 这类分数在线上只做轻量 heuristic，不做重 LLM judge
- 线上质量分的职责是趋势分析，不是学术评测
- 线上可增加 1% 到 5% 请求采样，做规则评分或模型评审，但结果应回写为聚合分布或样本报告，不直接暴露高基数字段


### 5.2 Import / Ingest 指标

#### 5.2.1 在线性能

必须建立：

- `source_create_total`
- `source_upload_total`
- `source_import_total`
- `ingest_end_to_end_duration_ms`
- `ingest_parse_duration_ms`
- `ingest_clean_duration_ms`
- `ingest_quality_score_duration_ms`
- `ingest_fallback_duration_ms`
- `ingest_chunk_duration_ms`
- `ingest_embedding_duration_ms`
- `ingest_persist_duration_ms`
- `ingest_ready_duration_ms`

#### 5.2.2 在线质量

必须建立：

- `ingest_markdown_quality_score`
- `ingest_parse_success_rate`
- `ingest_parse_success_rate_by_doc_type`
- `ingest_fallback_rate`
- `ingest_embedding_failure_rate`
- `ingest_content_ready_ratio`
- `ingest_parser_distribution`
- `ingest_ocr_trigger_rate`
- `ingest_title_hierarchy_recovery_rate`
- `ingest_list_recovery_rate`
- `ingest_table_recovery_rate`
- `ingest_image_recovery_rate`
- `ingest_link_recovery_rate`

说明：

- Markdown 质量分建议拆成结构完整度、可读性、噪声比例、标题层级、图片保留率
- 文档类型成功率至少按 `pdf`、`pdf_scanned`、`word`、`html`、`web` 分桶
- Markdown 结构完整率至少覆盖标题层级、列表、表格、图片、链接恢复
- 当前 worker 已经有 `quality_score` 和分阶段毫秒字段，可以直接发展成标准指标体系


### 5.3 AI Generation 指标

这里包含：

- Chat
- Summary

#### 5.3.1 在线性能

必须建立：

- `ai_request_total`
- `ai_request_duration_ms`
- `ai_first_token_ms`
- `ai_token_stream_duration_ms`
- `ai_prompt_tokens_total`
- `ai_completion_tokens_total`
- `ai_total_tokens_total`
- `ai_route_distribution`
- `ai_retrieval_context_count`

当前缺口：

- 目前只有 `observe_llm_call()`，还没有 `first token`
- 没有 chat route 质量与 retrieval 命中规模指标

#### 5.3.2 在线质量代理指标

建议建立：

- `ai_follow_up_rate`
- `ai_regenerate_rate`
- `ai_question_rewrite_rate`
- `ai_copy_rate`
- `ai_citation_click_rate`
- `ai_answer_length_distribution`

解释：

- 追问率：某次回答后短时间内同会话继续追问的比例
- 改写问题率：同一会话中用户在短时间内重问/改写同类问题的比例
- 复制率：用户复制回答内容的比例
- citation 点击率：如果前端支持 citation 点击，可反映 grounded answer 实用性

注意：

- 这些是线上代理指标，不等于离线质量基准


## 6. 多维度观测设计

### 6.1 当前阶段不做的日志分析能力

当前明确不做：

- 1 分钟级 ERROR 数量趋势
- TopN error signature
- 某 error signature 的突增检测

原因：

- 单机部署阶段，这类日志聚合收益没有核心业务指标高
- 这会分散 Search / Import / AI 三条主链路的建设精力
- 当前日志更应该服务于排障，而不是做日志分析平台

当前保留的日志要求：

- 所有核心业务都要有结构化 business event
- 所有异常都要带关键上下文字段
- 日志必须能通过 `request_id` / `trace_id` 回放单次过程


### 6.2 中间件与机器资源

应纳入 Prometheus：

- `node_exporter`
- `redis_exporter`
- `postgres_exporter`
- `kafka-exporter`（已存在）

观测面板：

- 机器：CPU、memory、disk usage、disk IO、network、load average、FD
- Redis：ops、hit rate、latency、memory、memory fragmentation、evictions、clients、rejected connections、slowlog
- PostgreSQL：connections、slow query、lock wait、deadlock、cache hit ratio、TPS；如果后续引入主从，再加 replication lag
- Kafka：producer throughput、consumer throughput、consumer lag、retry、DLQ、consumer health

关于 Redis bigkey / hotkey：

- Redis exporter 只能覆盖一部分通用指标
- `bigkey` / `hotkey` 更适合通过定时任务采样 `redis-cli --bigkeys`、`MEMORY USAGE`、`SLOWLOG GET`
- 这部分建议做成低频巡检任务，而不是请求路径实时埋点

这部分最重要的不是“全监控”，而是把基础设施指标和 3 条核心链路关联起来：

- Search 延迟 / 失败要能回看 Redis 命中率、PostgreSQL 慢查询、Kafka lag、机器 load
- Import 延迟 / 失败要能回看磁盘 IO、OCR 触发率、embedding 耗时、PostgreSQL 锁等待
- AI 延迟 / 首 token 退化要能回看 Redis 命中率、模型 provider 耗时、机器 load、Kafka 积压


### 6.3 手动 tracing 设计

因为当前是单机部署，tracing 不强调服务间拓扑，而强调函数级阶段拆解。

必须手动补 span 的路径：

- Search
  - `search.start`
  - `search.provider_call`
  - `search.result_map`
  - `search.result_persist`
  - `search.response_build`
- Import / Ingest
  - `ingest.fetch`
  - `ingest.parse`
  - `ingest.clean`
  - `ingest.quality_score`
  - `ingest.llm_fallback`
  - `ingest.parse_commit`
  - `ingest.chunk`
  - `ingest.embed`
  - `ingest.persist`
- AI Chat / Summary
  - `chat.prepare`
  - `chat.route`
  - `chat.retrieval`
  - `chat.prompt_build`
  - `chat.model_first_token`
  - `chat.model_stream`
  - `chat.finalize`
  - `summary.prepare`
  - `summary.cache_lookup`
  - `summary.prompt_build`
  - `summary.model_first_token`
  - `summary.finalize`

每个 span 建议带的 attribute：

- `user.id`
- `notebook.id`
- `article.id`（如果有）
- `business.phase`
- `provider`
- `model_name`
- `input_type`
- `search.mode`
- `search.execution`


### 6.4 高基数约束

必须明确禁止：

- 不要把 `query_text`、`user_id`、`doc_id`、`article_id`、`trace_id` 直接做成 Prometheus labels
- 不要把上述字段直接做成 Loki labels

原因：

- 这些字段会快速拉爆时序和索引基数
- Prometheus 适合聚合维度，不适合存原始业务主键
- Loki labels 适合低基数筛选键，高基数字段应留在日志正文 JSON 中

替代做法：

- Prometheus 只保留低基数维度，如 `operation`、`provider`、`model`、`route`、`status`、`input_type`
- 需要定位单次请求时，通过日志字段和 trace metadata 检索，不通过指标 labels 检索
- 文本型查询、完整回答、完整 citation 列表只放日志或 LangSmith，不放指标标签


## 7. 目标离线体系

### 7.1 离线闭环

离线体系不是“跑一批指标”就结束，而是完整闭环：

1. 数据集
2. 评测器
3. 基线结果
4. 版本对比
5. 发布门禁
6. 坏例子回流

要求：

- 每次 benchmark 都要产出可归档报告
- 基线结果要能按版本持久化
- 新版本结果必须和最近稳定基线做对比
- 坏例子要沉淀回 `cases/` 或数据集构造脚本，形成持续回归集


### 7.2 数据集层

新增目录建议：

```text
backend/evals/
  datasets/
    search/
    rag_qa/
    summary/
  dataset_builders/
  cases/
  reports/
  runners/
  k6/
  online_seed/
```

数据格式建议：

- JSONL
- 每条 case 带 `id`, `query`, `context`, `ground_truth`, `expected_sources`, `tags`, `difficulty`

脚本职责建议：

- `dataset_builders/`：离线数据集构造脚本
- `runners/`：benchmark 运行脚本
- `online_seed/`：在线数据创建脚本，用于压测和在线 dashboard 演示数据灌入
- `k6/`：压测脚本


### 7.3 Search 离线评估

需要做：

- Recall@K
- Precision@K
- NDCG@K
- MRR
- 导入转化率
- 新鲜度满足率
- 权威来源命中率

适用对象：

- 来源搜索
- 相关文章检索
- chunk evidence 检索

数据集分层建议：

- 高频头部查询
- 长尾自然语言查询
- 时效性强的查询
- 专业领域查询
- 明确需要权威来源的查询
- 导入后新文档可检索查询
- 失败 / 无结果 / 歧义查询
- 对抗样本：错别字、别名、缩写、时间限定、跨语种

标签至少包括：

- `query_intent`
- `domain`
- `freshness_requirement`
- `authority_requirement`
- `expected_docs`
- `acceptable_docs`
- `bad_docs`
- `corpus_version`

脚本交付：

- `backend/evals/runners/search_benchmark.py`
- `backend/evals/dataset_builders/build_search_dataset.py`


### 7.4 Import / Ingest 离线评估

建议按文档类型建子集：

- 可解析 PDF
- 扫描 PDF / OCR 场景
- Word / PPT / HTML
- 超长文档 / 坏文档 / 编码异常文档

评测指标分三层：

- 过程层：parse 成功率、阶段耗时、OCR 触发率
- 文本层：ROUGE、BERTScore、关键信息字段 exact match
- 结构层：标题树相似度、表格单元格恢复率、图片恢复率、链接恢复率、chunk 边界合理性

要求：

- 不要只给一个 ingest 总分
- 必须按文档类型、解析器、是否 OCR、是否 fallback 分维度出报告

脚本交付：

- `backend/evals/runners/ingest_benchmark.py`
- `backend/evals/dataset_builders/build_ingest_dataset.py`


### 7.5 Summary 离线评估

需要做：

- ROUGE
- BERTScore
- 事实一致性
- 简洁度
- 可读性

建议实现：

- ROUGE / BERTScore 走 deterministic script
- 事实一致性 / 可读性可用 LLM judge 离线跑批

脚本交付：

- `backend/evals/runners/summary_benchmark.py`
- `backend/evals/dataset_builders/build_summary_dataset.py`


### 7.6 Article QA / RAG 离线评估

需要做：

- retrieval
  - Context Precision
  - Context Recall
  - Hit Rate
- answer
  - Relevance
  - Groundedness
  - Completeness
  - Conciseness
  - Readability
- citation
  - 引用覆盖率
  - 引用正确率
  - 无依据断言率
- behavior
  - 安全拒答率
  - 工具调用正确率
  - 多轮一致性

组件建议：

- `Ragas` 作为第一优先级框架

原因：

- 它天然贴合 RAG 评估
- 对 relevance / faithfulness / context precision / context recall 支持较成熟

脚本交付：

- `backend/evals/runners/rag_benchmark.py`
- `backend/evals/dataset_builders/build_rag_dataset.py`


### 7.7 API 压测

目标：

- 搜索接口压测
- notebook detail 轮询压测
- summary/chat 接口压测
- 导入接口压测

组件选择：

- 主方案：`k6`
- 备选：`Locust`

选择理由：

- `k6` 更适合用阈值直接做 CI/CD 门禁
- `Locust` 更适合复杂用户行为和 Python 场景建模

本项目建议：

- 首发只上 `k6`
- 如果后续要模拟复杂用户旅程，再加 `Locust`

脚本交付：

- `backend/evals/k6/search-load.js`
- `backend/evals/k6/notebook-detail-poll.js`
- `backend/evals/k6/chat-stream.js`
- `backend/evals/k6/summary-stream.js`
- `backend/evals/k6/source-import.js`


### 7.8 在线数据创建脚本

为了让线上 dashboard、压测、离线回归都能快速拿到数据，需要提供在线数据创建脚本。

用途：

- 批量创建 notebook
- 批量灌搜索 session / import / article
- 批量触发 chat / summary
- 生成可观测面板需要的基础样本

建议交付：

- `backend/evals/online_seed/create_demo_notebooks.py`
- `backend/evals/online_seed/create_search_sessions.py`
- `backend/evals/online_seed/create_import_jobs.py`
- `backend/evals/online_seed/create_chat_threads.py`
- `backend/evals/online_seed/create_summary_runs.py`


## 8. 成熟方案与官方组件参考

建议参考的官方/主流资料：

- OpenTelemetry 文档：<https://opentelemetry.io/docs/>
- OpenTelemetry GenAI semantic conventions：<https://opentelemetry.io/docs/specs/semconv/gen-ai/>
- Prometheus histogram practices：<https://prometheus.io/docs/practices/histograms/>
- Prometheus recording rules：<https://prometheus.io/docs/practices/rules/>
- Loki recording rules：<https://grafana.com/docs/loki/latest/operations/recording-rules/>
- Tempo metrics generator：<https://grafana.com/docs/tempo/latest/metrics-generator/>
- Grafana k6 thresholds：<https://grafana.com/docs/k6/latest/using-k6/thresholds/>
- Locust writing a locustfile：<https://docs.locust.io/en/stable/writing-a-locustfile.html>
- Ragas metrics overview：<https://docs.ragas.io/en/stable/concepts/metrics/overview/>
- LangSmith observability：<https://docs.langchain.com/langsmith/observability>
- LangSmith evaluation：<https://docs.langchain.com/langsmith/evaluation>

需要特别注意：

- OpenTelemetry 的 GenAI 语义约定仍在发展中，现阶段适合作为未来兼容方向，不适合直接替代你的核心业务指标体系
- Prometheus histogram bucket 要围绕真实毫秒级分布设计，不能只用默认 bucket
- Loki 更适合原始日志检索和趋势聚合，不要把它当明细数仓
- LangSmith 适合承接在线与离线 LLM/RAG 评估，不需要因为引入 Ragas 而替换掉


## 9. 具体改造计划

### Phase 0: 统一规范与盘点

目标：

- 不先加大量指标，先定义统一规范

产出：

- Search / Import / AI 三条链路的事件字典
- metric naming 规范
- trace span 命名规范
- dashboard 命名和分层规范
- benchmark 报告格式规范
- 在线造数脚本输入输出规范
- 离线数据集 schema 规范

代码改动点：

- `backend/app/infra/telemetry/metrics.py`
- `backend/app/infra/telemetry/logging.py`
- `backend/app/infra/telemetry/tracing.py`
- `backend/app/api/middleware.py`


### Phase 1: 核心业务在线观测

范围：

- 只做 Search / Import / AI

Search：

- 增加阶段耗时 metrics
- 增加结果数 / 导入数 / 转化率 metrics
- 增加线上质量代理评分日志与 metrics
- 增加 search 手动 trace spans

Import：

- 打通 parse / clean / quality / fallback / chunk / embed / persist 完整阶段指标
- 统一 worker 结构化事件
- 增加 Markdown 质量评分 histogram
- 增加 ingest 手动 trace spans

AI：

- 补 `first_token_ms`
- 补 route / retrieval / prompt / model / finalize 手动 spans
- 增加 follow-up / regenerate / rewrite / copy 等质量代理指标

交付物：

- `core-business-overview` dashboard
- `search-business` dashboard
- `import-business` dashboard
- `ai-generation` dashboard


### Phase 2: tracing 深化与基础设施观测

范围：

- trace 链路细化
- 中间件与机器资源

改造内容：

- Search / Import / AI span 树细化
- 让日志字段和 trace span attributes 对齐
- 接 `node_exporter`
- 接 `redis_exporter`
- 接 `postgres_exporter`
- 整理 Kafka dashboard
- 增加 Redis bigkey / hotkey 巡检任务


### Phase 3: 离线基准测试体系

范围：

- Search benchmark
- RAG QA benchmark
- Summary benchmark
- API 压测

改造内容：

- 建 `backend/evals/`
- 沉淀数据集
- 补在线造数脚本
- 写统一 runner
- 写压测脚本
- 产出 JSON / Markdown 报告
- 用 Prometheus / Grafana 可视化 benchmark 结果


## 10. 推荐的首批落地清单

如果要从今天开始做，我建议顺序是：

1. 先补统一业务事件字典与命名规范
2. 重写 `metrics.py`，围绕 Search / Import / AI 建立完整指标
3. 在 search / ingest / ai 路径补 trace spans
4. 建 4 张业务 dashboard
5. 接入 `node_exporter` / `redis_exporter` / `postgres_exporter`
6. 建 `backend/evals/`，先落在线造数脚本
7. 再落 Search / RAG / Summary 的 benchmark 脚本
8. 最后补 API 压测脚本和回归阈值


## 11. 当前仓库的具体修改点建议

第一批一定会改到：

- `backend/app/infra/telemetry/metrics.py`
- `backend/app/infra/telemetry/logging.py`
- `backend/app/infra/telemetry/tracing.py`
- `backend/app/api/middleware.py`
- `backend/app/modules/search/sessions/service.py`
- `backend/app/modules/search/sources/import_service.py`
- `backend/app/modules/search/sources/manual_service.py`
- `backend/app/modules/ingest/articles/service.py`
- `backend/app/modules/ingest/articles/worker.py`
- `backend/app/modules/ingest/indexing/pipeline.py`
- `backend/app/modules/ai/chat/service.py`
- `backend/app/modules/ai/chat/context_builder.py`
- `backend/app/modules/ai/summary/service.py`
- `backend/app/modules/ai/summary/workflow.py`
- `docker/prometheus/prometheus.yml`
- `docker/grafana/dashboards/*`
- `backend/evals/online_seed/*`
- `backend/evals/runners/*`
- `backend/evals/k6/*`

后续批次再改：

- `docker/otel-collector/config.yaml`
- 新增 exporter 相关 compose / scrape 配置
- 更完整的 benchmark dataset builder


## 12. 结论

当前项目不是“没有可观测性”，而是“只有基础技术可观测性，没有围绕核心业务建立完整体系”。

正确改造方式不是把所有东西都打一遍点，而是：

1. 先围绕 Search / Import / AI 三条业务链建立清晰的 logging / metrics / tracing 边界
2. tracing 以手动 span 为核心，优先拆解函数阶段耗时
3. 再补基础设施 exporter、在线造数、离线 benchmark 与压测脚本

短期最重要的不是多加几个通用监控图，而是把“搜索质量、导入质量、AI 生成质量”变成持续可追踪、可对比、可回归的数据体系。
