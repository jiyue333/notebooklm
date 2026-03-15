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







目前项目的完成度基本能通过baseline，我想从下面五个方面切入做改进。请你分别进行调研业界的成熟方案，然后在docs目录下创建ADR proposal文档。

1. 搜索链路：我的目标是提高检索的质量，不考虑对模型层做改进，只考虑工程。我的预想是预设高质量站点如arxiv，用关键词检索配合 再配合exa （auto模式也可以优化，根据任务的复杂度选择，fast模式搜索30篇，deep模式搜索五十篇）。然后做一个排序精选出20篇文章（不一定要是网页文章，也可以是论文pdf）。然后我们目前有一个搜索质量评价的算法，你可以把算法情况列在ADR下，然后分析还有什么值得提升的。
2. 解析链路：我们目前有解析质量评价，但是从我测试情况来看效果并不理想。我们应该分析质量评价算法（同理把现有算法评价列出来），然后优化路由决策，优化解析方案等等。
3. summary链路：这个同理，把现有项目的summary质量算法分析列出来，然后调研算法有哪些改进点，summary我们可以做哪些工程化改进（不考虑模型层改进）
4. 性能链路：redis缓存，postgre调优，系统瓶颈，各种链路耗时调优，只需要重点关注我们的主链路（搜索，导入，summary，chat）就可以了。可以配合我们现有的观测性指标一起看。
5. 稳定性链路：postgre..... redis缓存一致性..... kafka失败幂等...... 安全性sql xss 加密......











我想请你帮我一起设计一个知识助手 / 研究助手类产品的核心链路。

先说明我的期待：我这次不只是想看“业界有哪些成熟方案”，我更想看的是，如果让你来设计这个系统，你会怎么思考、怎么拆解、会提出哪些有价值的方案 idea。

我不希望你只是做资料综述，或者罗列一些通用最佳实践。我更希望你站在一个懂计算机系统、搜索、信息处理、内容理解的技术设计者角度，主动提出你的设计思路。可以参考业界，但重点是“你会怎么设计”。

这个产品的核心业务流程分成三步：

1. Search
用户输入一个主题、问题或研究任务，系统去搜索相关资料，目标是尽可能找到高质量、相关、可信、覆盖面合理的候选内容。资料类型可以包括网页内容、论文、PDF 等。

2. Ingest
系统把选中的资料导入进来，并解析成适合后续处理的内容。这里的重点是把不同类型的输入源，比如网页、普通 PDF、扫描版 PDF、Word、Markdown 等，尽量稳定地转成高质量、适合下游处理的 markdown 文本或文档表示。

3. Summary
系统基于导入后的内容生成摘要，帮助用户快速理解资料。摘要不仅要简洁，还要尽量保证信息覆盖、结构清晰、事实一致，并方便后续继续问答或深入阅读。

我希望你重点围绕 Search、Ingest、Summary 这三个链路，提出“如果是你，你会怎么设计”的方案。

这里的“方案”不是泛泛而谈，而是希望你给出比较具体的 idea。例如 Search 链路里，我期待看到类似这样的思路粒度：

- 预设高质量站点，如 arXiv、PubMed、政府/高校/实验室网站
- 关键词检索配合 Exa、Perplexity 之类的成熟搜索 API
- 根据任务复杂度选择不同搜索模式
- fast 模式搜索 30 篇，deep 模式搜索 50 篇
- 对网页、论文、PDF 混合召回
- 再做排序和精选，最终保留 20 篇高质量候选
- 使用 recency / authority / credibility / professional 等评价指标，创建一个综合得分算法

我想看到的是这种“你会怎么搭这个链路”的思路，而不是只说“可以做 reranking、可以做 query expansion”这种抽象结论。

请你分别从 Search、Ingest、Summary 三个链路展开，并按下面的方式输出。

对于每一条链路，请尽量包含：

1. 这条链路的核心目标
  你认为这条链路真正要优化的目标是什么，最终是为了解决什么问题。

2. 这条链路的问题

  比如search链路

  - 如何提升结果相关性、权威性、新鲜度和覆盖度
  - 如何兼顾网页内容和论文/PDF 等不同来源
  - 如何设计多阶段检索流程，例如召回、过滤、重排、精选
  - 如何做高质量来源优先、站点白名单、领域路由等策略
  - 如何根据任务复杂度设计不同搜索模式，比如 fast / standard / deep
  - 当前业界在 search aggregation、reranking、query routing、source prior、diversity 控制方面有哪些成熟方案和新趋势
  - Search 质量应该如何评估，常见指标和评测方法有哪些
  - ........

3. 你会怎么设计这条链路
  请尽量具体，给出成体系的设计思路，而不是零散概念。
  比如：
- 输入是什么
- 中间要经过哪些阶段
- 每个阶段做什么判断
- 如何路由
- 如何筛选
- 如何 fallback
- 最终输出什么样的结果

3. 你会提出哪些值得考虑的方案 idea
我希望你尽量多给一些有启发性的设计想法，不要只局限于成熟方案。
可以是工程上可落地的，也可以是偏前沿、但值得考虑的方向。
重点是：这些 idea 要具体，要像是在设计一个真实系统。

4. 这些方案的优缺点和适用场景
请比较不同设计思路分别适合什么场景，有什么 tradeoff。

5. 如果让你来拍板，你会优先选哪种方案组合
也就是说，在你提出多种 idea 之后，请你给出一个你自己最认可的组合方案，并说明为什么。

6. 你会怎么评估这条链路做得好不好
也就是：
- 你会看哪些指标
- 你会怎么做 benchmark
- 你会怎么判断这个设计是否真的有效

另外我希望你特别注意下面几点：

- 不要只做“业界方案综述”，重点是你自己的设计思考
- 可以参考成熟产品，但不要停留在“别人怎么做”
- 我更关心方案 idea、系统拆解方式、路由逻辑、模块组合方式
- 可以大胆提出组合式方案、分层方案、多模式方案
- 暂时不需要考虑具体代码落地，也不需要绑定某个技术栈
- 重点是先把 Search / Ingest / Summary 这三条链路“应该怎么设计”想清楚
- 请尽量写得具体，不要只写抽象名词

为了避免回答得太空，请你在 Search、Ingest、Summary 三部分里，都尽量给出“像搭积木一样”的流程化设计，而不是只有原则。







我想请你帮我调研一个知识助手/研究助手类产品的方案设计。

这个产品的核心业务流程很简单，分成三步：

1. Search
用户输入一个主题、问题或研究任务，系统去搜索相关资料，目标是尽可能找到高质量、相关、可信、覆盖面合理的候选内容。资料类型可以包括网页、论文、PDF 等。

2. Ingest
系统把选中的资料导入进来，并解析成适合后续处理的内容。这里的重点是把不同类型的输入源，比如网页、普通 PDF、扫描版 PDF、Word、Markdown 等，尽量稳定地转成高质量、结构化、可读、可下游的 markdown 表示。

3. Summary
系统基于导入后的内容生成摘要，帮助用户快速理解资料。摘要不仅要简洁，还要尽量保证信息覆盖、结构清晰、事实一致、方便后续继续问答或深入阅读。

我这次希望你重点调研这三条链路的“最佳实践”和“前沿方案”，目标不是泛泛而谈，而是希望你能总结出目前业界成熟可落地的方案，以及值得关注的前沿方向。

请你分别从 Search、Ingest、Summary 三个链路展开调研，并尽量回答下面这些问题：

一、Search 链路
我的目标是提高检索质量，重点关注：
- 如何提升结果相关性、权威性、新鲜度和覆盖度
- 如何兼顾网页内容和论文/PDF 等不同来源
- 如何设计多阶段检索流程，例如召回、过滤、重排、精选
- 如何做高质量来源优先、站点白名单、领域路由等策略
- 如何根据任务复杂度设计不同搜索模式，比如 fast / standard / deep
- 当前业界在 search aggregation、reranking、query routing、source prior、diversity 控制方面有哪些成熟方案和新趋势
- Search 质量应该如何评估，常见指标和评测方法有哪些

二、Ingest 链路
我的目标是提高解析后的内容质量和稳定性，重点关注：
- 如何针对不同来源类型设计解析路由
- 网页抽取、PDF 解析、扫描 PDF OCR、Office 文档解析有哪些成熟做法
- 如何提升结构保真度，比如标题、段落、列表、表格、图片说明、引用关系等
- 如何设计 fallback 机制和路由决策，让系统在失败或低质量情况下自动切换方案
- 如何定义“解析质量”，以及怎样建立更接近真实可用性的评价体系
- 当前业界在文档解析、layout-aware parsing、OCR routing、cleaning/normalization 方面有哪些成熟方案和前沿方向

三、Summary 链路
我的目标是提高摘要的实用性和稳定性，重点关注：
- 如何做长文摘要、分层摘要、章节级摘要、结构化摘要
- 如何让摘要更适合后续继续追问、定位原文和知识消费
- 如何平衡摘要长度、信息覆盖率、可读性和事实一致性
- 当前业界在 hierarchical summarization、outline-first summarization、evidence-linked summary、incremental summary 等方面有哪些成熟方案和前沿方向
- Summary 质量应该如何评估，除了 ROUGE 这类传统指标，还有哪些更实用的评测方法

希望你的输出不是零散观点，而是对每条链路都给出一个结构化结论。建议每条链路至少包含：

1. 这条链路的核心目标和常见难点
2. 业界成熟方案综述
3. 值得关注的前沿方案
4. 不同方案的优缺点、适用场景和成本
5. 你认为最值得优先采用的方案组合
6. 建议配套的评测指标和验证方法

另外，请你尽量区分：
- 已经被广泛验证、适合直接落地的成熟方案
- 还比较前沿、值得关注但实现成本或不确定性更高的方案

不需要假设现有代码结构，也不需要围绕某个具体技术栈来回答。重点是从业务流程和产品目标出发，帮我梳理 Search、Ingest、Summary 这三条链路目前最值得参考的最佳实践和前沿方向。
