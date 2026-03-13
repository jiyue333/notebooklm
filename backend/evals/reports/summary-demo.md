# NotebookLM Summary Benchmark

## Summary

- **benchmark**: summary
- **generated_at**: 2026-03-13T03:10:42.704676+00:00
- **cases**: 4

## Metadata

- **dataset**: backend/evals/datasets/summary/demo-summary-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/summary-demo.jsonl
- **with_bert_score**: False

## Metrics

| Metric | Value |
| --- | ---: |
| rouge_1_f1 | 0.7496 |
| rouge_l_f1 | 0.7371 |
| required_phrase_hit_rate | 1.0000 |
| compression_ratio | 0.0737 |
| summary_length_avg | 147.0000 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| metrics.compression_ratio | 0.0737 | 0.1700 | -0.0963 | improved |
| metrics.required_phrase_hit_rate | 1.0000 | 0.8400 | 0.1600 | improved |
| metrics.rouge_1_f1 | 0.7496 | 0.7100 | 0.0396 | improved |
| metrics.rouge_l_f1 | 0.7371 | 0.6700 | 0.0671 | improved |
| metrics.summary_length_avg | 147.0000 | 176.0000 | -29.0000 | improved |
