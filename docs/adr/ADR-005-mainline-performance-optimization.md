# ADR-005: 主链路性能优化

状态：Proposal  
日期：2026-03-14

## 背景

本 ADR 只关注四条主链路：

- Search
- Import / Ingest
- Summary
- Chat

当前系统已经有比较完整的观测基础：

- `backend/app/infra/telemetry/metrics.py`
- `docs/observability-structure.md`
- `docker/grafana/dashboards/search-dashboard.json`
- `docker/grafana/dashboards/ingest-dashboard.json`
- `docker/grafana/dashboards/llm-dashboard.json`
- `docker/grafana/dashboards/infra-dashboard.json`

当前也已经具备一定的性能基础设施：

- PostgreSQL + pgvector
- Redis
- Kafka
- GIN / HNSW 索引
- summary / notebook / search session 缓存

但当前性能优化仍主要停留在“有指标”，还没有进入“以主链路瓶颈为中心”的治理。

## 当前实现概况

**Search**：瓶颈包括多引擎 fan-out latency、top candidates 的 enrichment / deep fetch、去重与 canonicalization、LLM task parsing / rerank。优化方向：两阶段搜索（第一阶段轻量召回 + 轻打分，第二阶段只对 top N 做 enrichment / rerank，不要一上来对 50 个结果全抓全文）；对相似任务做 query lattice 缓存（task parse、query family、domain pack、source priors）；对 URL / DOI / PMID / arXiv id 建 content cache / metadata cache，同一来源被反复搜到时避免重复抓取；先 dedup 再深抓取，能省很多网络和 rerank 成本；按模式切预算（fast 模式限制 query families 数量，deep 模式才启用 seed expansion / heavier rerank）；对特定源做速率治理（如 PubMed E-Utilities 默认 3 rps，学术 lane 需要独立队列和 rate limiter）。

**Import / Ingest**：瓶颈包括文件下载和浏览器渲染、PDF 解析、OCR / VLM、parser ensemble 并行跑太重、embedding / section summary 构建。优化方向：先用便宜路由（MIME fast router），别让所有文档都走重型 parser；OCR / VLM 只打可疑页，不打整篇；progressive ingest（先正文，再 toc，再 refs/citations，再 section summaries / embeddings，首屏体验更快）；artifact hash cache，相同文件内容不重复解析；并行但不全并行，先 cheap probe 再决定是否开第二 parser；section-level embedding batch，先 section / block cluster，后续按需细化。

**Summary**：瓶颈包括长文输入上下文太大、分层摘要多轮调用、judge / verifier 增加额外开销。优化方向：把 summary 建在 ingest 产物上（若已有 toc、section roles、block graph、section summaries 则不用从原文整扫）；长度路由（短文直接 summarization，长文分层，差文保守摘要）；按 article_hash + summary_prompt_version + locale 做 summary cache；judge / verifier 只打最后 1–2 个候选；变更感知（文章没变不因 notebook 变化重算 canonical summary，个性化 summary 延迟到真正需要时再做）。

**Chat**：瓶颈包括 route 判错后触发错误检索消耗 fan-out、recommendation 需扫全 corpus 的 article-level memory、notebook-research 需 article shortlist + section retrieval + synthesis 天然更重、verifier / grounding checker 拉长尾延迟。优化方向：cheap router 先行，80% scope 判定用便宜路由器，高熵样本再升级；多级索引（article-grounded 先打 cursor-local，recommendation 先打 article synopsis，notebook-research 先打 article shortlist），先粗后细；为 recommendation 预计算 article synopsis、tags/entities/methods、article embedding、notebook membership；research lane 做 context budgeting（article shortlist 5–8，每篇证据 section 1–3，总 evidence blocks 上限 20–30）；verifier 只校验最终答案；按 lane 分开 SLA（article-grounded 最短延迟，general 次短，recommendation 中等，notebook-research 允许更长但必须稳定）。

### DB / Cache / Infra

当前配置能看出的现实约束：

- DB pool：`database_pool_size=10`, `database_max_overflow=20`
- Redis 已用于 notebook detail、search session、settings、summary cache
- pgvector 已建 HNSW 索引
- 没有看到 `pg_stat_statements` 已集成到 repo 运行面
- 还没有看到主链路级的“排队时间/缓存击穿/SQL 指纹”闭环

## 调研到的业界成熟方案

### 1. 先用 SQL 指纹与执行计划抓热点

PostgreSQL 官方给出两条非常成熟的性能治理基线：

- `pg_stat_statements`：追踪 planning / execution 统计
- `EXPLAIN ANALYZE`：对热点 SQL 看真实计划、行数估计偏差、buffer 行为

参考：

- [pg_stat_statements](https://www.postgresql.org/docs/current/pgstatstatements.html)
- [Using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)

### 2. autovacuum / analyze 是 OLTP 主链路性能的基础设施

PostgreSQL 官方明确强调：

- `VACUUM` 用于回收死元组、防止膨胀、避免 wraparound
- `ANALYZE` 用于更新 planner statistics
- autovacuum 是“强烈推荐”的默认能力，但高更新表往往需要调优阈值

参考：[Routine Vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)

### 3. 缓存优化不是“多加 TTL”，而是控制一致性与淘汰策略

Azure 的 Cache-Aside 模式和 Redis 官方 eviction 文档都强调：

- 缓存生命周期要匹配访问模式
- eviction policy 必须和 workload 匹配
- cache-aside 天生不保证强一致，需要显式处理

参考：

- [Cache-Aside pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
- [Redis key eviction](https://redis.io/docs/latest/develop/reference/eviction/)

## 决策

采用“链路 SLO + SQL 指纹治理 + 缓存抗抖 + 主链路专项优化”的方案。

## 决策细节

### 决策 1：为四条主链路建立明确 SLO

建议先定义：

- Search
  - `p50/p95 search total latency`
  - `p95 provider latency`
- Import
  - `p95 parse-ready latency`
  - `p95 end-to-end ingest latency`
- Summary
  - `p95 TTFT`
  - `p95 summary total latency`
- Chat
  - `p95 TTFT`
  - `p95 response total latency`

然后让 Grafana 和报警围绕这些 SLO，而不是只看原始 histogram。

### 决策 2：补齐 PostgreSQL 运行面治理

建议：

1. 启用 `pg_stat_statements`
2. 开启 query fingerprint 级别热点分析
3. 对以下表做专门 autovacuum / analyze 调优：
   - `articles`
   - `article_chunks`
   - `search_results`
   - `search_sessions`
   - `jobs`
4. 对高频 SQL 形成固定 `EXPLAIN ANALYZE` 检查单

重点关注：

- `list_pending_publish_jobs`
- `list_search_results`
- notebook detail 拼装查询
- chunk retrieval / article retrieval
- summary cache 查询

### 决策 3：按链路做缓存抗抖，不只是继续堆 TTL

当前 TTL 已经存在，但还应增加：

- singleflight / request coalescing
- stale-while-revalidate
- versioned cache invalidation
- 大对象压缩或裁剪

优先级建议：

1. `notebook_detail`
2. `search_session`
3. `summary_cache`

### 决策 4：Search / Ingest / Summary / Chat 各自专项优化

四条链路的瓶颈与专项优化见上文「当前实现概况」。

## 具体落地建议

### Phase 1：观测补强

新增：

- queue wait time
- DB fingerprint top-N
- cache miss storm 指标
- notebook detail rebuild latency
- retrieval latency 分拆

### Phase 2：DB 与缓存

1. 启用 `pg_stat_statements`
2. 热 SQL 做 `EXPLAIN ANALYZE`
3. 为 `jobs`、`search_sessions` 增加状态型查询优化
4. 对 Redis cache 引入 singleflight

### Phase 3：链路专项

按收益排序：

1. notebook detail cache 抗抖
2. search response shortlist 化，减少无效结果
3. ingest parse 结果复用
4. summary section cache

## 需要新增或调整的指标

建议新增：

- `db.query_fingerprint_duration_ms`
- `db.query_fingerprint_calls`
- `cache.singleflight_wait_ms`
- `cache.stale_served_total`
- `search.shortlist_build_ms`
- `ingest.parse_result_reuse_total`
- `summary.section_cache_lookup_total`
- `chat.retrieval_latency_ms`

## 风险与权衡

- `pg_stat_statements.track_planning` 有额外开销，应先只开执行统计或灰度开启
- 缓存 singleflight 会增加代码复杂度
- per-table autovacuum 参数需要结合真实数据量调优

## 验收标准

- 四条主链路都有明确 p95 基线
- 热 SQL 能按 fingerprint 排序定位
- notebook detail 与 summary cache 的 miss storm 显著减少
- ingest 与 chat 的主要瓶颈不再只能靠日志猜

## 参考资料

- [PostgreSQL pg_stat_statements](https://www.postgresql.org/docs/current/pgstatstatements.html)
- [PostgreSQL routine vacuuming](https://www.postgresql.org/docs/current/routine-vacuuming.html)
- [PostgreSQL using EXPLAIN](https://www.postgresql.org/docs/current/using-explain.html)
- [Cache-Aside pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)
- [Redis key eviction](https://redis.io/docs/latest/develop/reference/eviction/)

