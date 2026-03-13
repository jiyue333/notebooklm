# NotebookLM Search Benchmark

## Summary

- **benchmark**: search
- **generated_at**: 2026-03-13T03:10:42.704654+00:00
- **cases**: 6
- **k**: 5

## Metadata

- **dataset**: backend/evals/datasets/search/demo-search-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/search-demo.jsonl

## Metrics

| Metric | Value |
| --- | ---: |
| recall_at_k | 1.0000 |
| precision_at_k | 0.4000 |
| mrr | 0.8333 |
| ndcg_at_k | 0.9205 |
| freshness_satisfaction_rate | 0.8333 |
| authority_hit_rate | 0.8333 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| metrics.authority_hit_rate | 0.8333 | 0.7600 | 0.0733 | improved |
| metrics.freshness_satisfaction_rate | 0.8333 | 0.8100 | 0.0233 | improved |
| metrics.mrr | 0.8333 | 0.7300 | 0.1033 | improved |
| metrics.ndcg_at_k | 0.9205 | 0.7700 | 0.1505 | improved |
| metrics.precision_at_k | 0.4000 | 0.6200 | -0.2200 | regressed |
| metrics.recall_at_k | 1.0000 | 0.7900 | 0.2100 | improved |
