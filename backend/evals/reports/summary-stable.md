# NotebookLM Summary Benchmark

## Summary

- **benchmark**: summary
- **generated_at**: 2026-03-13T04:30:15.144017+00:00
- **cases**: 6

## Metadata

- **dataset**: backend/evals/datasets/summary/stable-summary-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/summary-stable.jsonl
- **with_bert_score**: False

## Metrics

| Metric | Value |
| --- | ---: |
| rouge_1_f1 | 0.8117 |
| rouge_l_f1 | 0.7949 |
| required_phrase_hit_rate | 0.9444 |
| compression_ratio | 0.0749 |
| summary_length_avg | 148.5000 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| metrics.compression_ratio | 0.0749 | 0.0749 | 0.0000 | unchanged |
| metrics.required_phrase_hit_rate | 0.9444 | 0.9444 | 0.0000 | unchanged |
| metrics.rouge_1_f1 | 0.8117 | 0.8117 | 0.0000 | unchanged |
| metrics.rouge_l_f1 | 0.7949 | 0.7949 | 0.0000 | unchanged |
| metrics.summary_length_avg | 148.5000 | 148.5000 | 0.0000 | unchanged |
