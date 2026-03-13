# NotebookLM Search Benchmark

## Summary

- **benchmark**: search
- **generated_at**: 2026-03-13T04:30:14.966947+00:00
- **cases**: 10
- **k**: 5

## Metadata

- **dataset**: backend/evals/datasets/search/stable-search-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/search-stable.jsonl

## Metrics

| Metric | Value |
| --- | ---: |
| recall_at_k | 0.9000 |
| precision_at_k | 0.3400 |
| mrr | 0.9000 |
| ndcg_at_k | 0.9000 |
| freshness_satisfaction_rate | 0.9000 |
| authority_hit_rate | 0.9000 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| metrics.authority_hit_rate | 0.9000 | 0.9000 | 0.0000 | unchanged |
| metrics.freshness_satisfaction_rate | 0.9000 | 0.9000 | 0.0000 | unchanged |
| metrics.mrr | 0.9000 | 0.9000 | 0.0000 | unchanged |
| metrics.ndcg_at_k | 0.9000 | 0.9000 | 0.0000 | unchanged |
| metrics.precision_at_k | 0.3400 | 0.3400 | 0.0000 | unchanged |
| metrics.recall_at_k | 0.9000 | 0.9000 | 0.0000 | unchanged |
