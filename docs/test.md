# =============== 在线测评架构 ===============

当前在线测评不是额外建设一套独立系统，而是复用线上请求、tracker 埋点、Prometheus 和 Grafana 做增量评审。

## Search 在线测评

Search 完成后会做确定性采样：

1. 规则评审
2. 可选 LLM judge
3. 坏例子回流

线上产物：

- Prometheus 指标
  - `notebooklm_search_review_samples_total`
  - `notebooklm_search_review_score`
  - `notebooklm_search_review_bad_cases_total`
- JSONL 文件
  - `backend/evals/reports/search_samples/*.jsonl`
  - `backend/evals/reports/search_bad_cases/*.jsonl`

## AI 在线测评

AI 在线测评分两层：

### 行为代理

- `follow_up`
- `citation_open`
- `answer_copy`
- `summary_copy`

### 在线 judge

对抽样的 chat / summary 结果做 LLM 评审，维度包括：

- `groundedness`
- `faithfulness`
- `completeness`
- `overall`

线上产物：

- Prometheus 指标
  - `notebooklm_ai_online_review_total`
  - `notebooklm_ai_online_review_score`
  - `notebooklm_ai_online_review_bad_cases_total`
- JSONL 文件
  - `backend/evals/reports/ai_reviews/*.jsonl`
  - `backend/evals/reports/ai_bad_cases/*.jsonl`

## Import / Ingest 在线测评

Import / Ingest 在线测评当前已经覆盖文档类型维度，不再只有 `input_type` 聚合。

重点指标：

- `notebooklm_ingest_doc_type_total`
- `notebooklm_ingest_doc_type_quality_score`
- `notebooklm_ingest_doc_type_structure_score`

因此现在可以直接观察：

- PDF、扫描 PDF、Word、PowerPoint、HTML、Markdown、纯文本的 parse 成功率
- 各文档类型的标题、列表、表格、图片、链接恢复率

## Redis 在线巡检

Redis 巡检由 scheduler 周期触发，也可以手动执行。

线上产物：

- Prometheus 指标
- `backend/evals/reports/redis/*.json`

用途：

- bigkey / hotkey 发现
- 与 notebook detail、search、AI 延迟联动排查

# =============== 离线测评架构 ===============

离线测评是一条完整流水线：

```text
cases
  -> datasets
  -> predictions / parsed results
  -> benchmark runners
  -> json / markdown reports
  -> prometheus textfile
  -> Grafana benchmark dashboard
```

## Search benchmark

数据来源：

- `backend/evals/cases/search/*`
- `backend/evals/datasets/search/*`
- `backend/evals/reports/predictions/search-*.jsonl`

指标：

- Recall@K
- Precision@K
- MRR
- NDCG@K
- freshness satisfaction rate
- authority hit rate

## Ingest benchmark

数据来源：

- `backend/evals/cases/ingest/*`
- `backend/evals/datasets/ingest/*`
- `backend/evals/reports/predictions/ingest-*.jsonl`

指标分三层：

- 过程层
  - parse success
  - OCR 触发率
  - parse / clean 耗时
- 文本层
  - exact match
  - required phrase hit rate
  - BERTScore
- 结构层
  - title_hierarchy
  - list
  - table
  - image
  - link

## Summary benchmark

数据来源：

- `backend/evals/cases/summary/*`
- `backend/evals/datasets/summary/*`
- `backend/evals/reports/predictions/summary-*.jsonl`

指标：

- ROUGE-1 F1
- ROUGE-L F1
- required phrase hit rate
- BERTScore
- compression ratio
- summary length

## RAG / QA benchmark

数据来源：

- `backend/evals/cases/rag_qa/*`
- `backend/evals/datasets/rag_qa/*`
- `backend/evals/reports/predictions/rag-*.jsonl`

指标分四层：

- retrieval
- answer
- citation
- behavior

RAG 评测支持两种模式：

1. 合并已有 Ragas 结果
2. 通过 `--with-ragas` 直接运行 Ragas

# =============== 数据流 ===============

## Profile

当前 benchmark 资产分为两个 profile：

- `demo`
- `stable`

默认运行 `stable`，因为它用于回归对比和基线门禁；`demo` 主要用于快速通路验证。

## 门禁

benchmark runner 现在不只是生成报告，还支持 baseline 门禁：

- `--fail-on-regression`

当任一指标相对 baseline 回退时，runner 会直接返回非零退出码。

这使它可以作为：

- 本地回归门禁
- CI 门禁
- 发布前校验入口

## k6 的角色

`backend/evals/k6/*` 负责接口压力测试，不参与质量评分。

当前统一入口已经接到 `scripts/benchmark.sh load-test`，覆盖：

- search
- import
- notebook detail poll
- chat stream
- summary stream

# =============== 运行入口 ===============

## 在线入口

统一通过：

```bash
./scripts/online.sh seed notebooks --count 3
./scripts/online.sh seed search
./scripts/online.sh seed import
./scripts/online.sh seed chat
./scripts/online.sh seed summary
./scripts/online.sh seed all --count 3
./scripts/online.sh inspect redis
./scripts/online.sh show search-samples
./scripts/online.sh show redis-report
```

说明：

- `search/import/chat/summary` 都支持不传 `--input` 的 one-click 模式
- 也支持通过 `--input` 传自定义 JSONL

## 离线入口

统一通过：

```bash
./scripts/benchmark.sh build-datasets all
./scripts/benchmark.sh run all
./scripts/benchmark.sh gate all
./scripts/benchmark.sh run ingest stable --with-bert-score
./scripts/benchmark.sh run rag stable --with-ragas --ragas-model gpt-4o-mini
./scripts/benchmark.sh load-test search
./scripts/benchmark.sh load-test chat
./scripts/benchmark.sh show reports
```

说明：

- `run` 和 `gate` 默认 profile 为 `stable`
- `gate` 会自动启用 baseline 回归门禁
- `load-test` 通过 `k6` 运行压测脚本
