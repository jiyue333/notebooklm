# ADR Proposals

日期：2026-03-14  
状态：Proposal

本目录收录 NotebookLM 下一阶段的六份 ADR proposal：四条主链路设计（Search / Ingest / Summary / Chat）与两条横切 ADR（性能优化、稳定性与安全）。文档全部基于当前仓库实现、现有评测/观测代码，以及外部成熟方案调研形成。

索引：

1. [ADR-001 Search 链路](./ADR-001-search-retrieval-quality-pipeline.md)
2. [ADR-002 Ingest 链路](./ADR-002-parse-pipeline-and-quality-evaluation.md)
3. [ADR-003 Summary 链路](./ADR-003-summary-pipeline-and-quality-evaluation.md)
4. [ADR-004 Chat 链路](./ADR-004-chat-pipeline.md)
5. [ADR-005 主链路性能优化](./ADR-005-mainline-performance-optimization.md)
6. [ADR-006 稳定性与安全性加固](./ADR-006-stability-security-hardening.md)

统一约束：

- 优先做工程化改进，不以“换更强模型”作为主方案。
- Proposal 里的“当前实现”以仓库现状为准，重点参照：
  - `backend/app/modules/search/*`
  - `backend/app/modules/ingest/*`
  - `backend/app/modules/ai/summary/*`
  - `backend/evals/runners/*`
  - `backend/app/infra/telemetry/metrics.py`
  - `docker/grafana/dashboards/*.json`
- 所有 ADR 都明确区分：
  - 当前算法/现状
  - 业界成熟模式
  - 建议决策
  - 分阶段落地
  - 需要新增的指标与验收标准

