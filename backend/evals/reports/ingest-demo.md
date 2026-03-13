# NotebookLM Ingest Benchmark

## Summary

- **benchmark**: ingest
- **generated_at**: 2026-03-13T03:10:42.704597+00:00
- **cases**: 5

## Metadata

- **dataset**: backend/evals/datasets/ingest/demo-ingest-dataset.jsonl
- **results**: backend/evals/reports/predictions/ingest-demo.jsonl
- **with_bert_score**: False

## Process Metrics

| Metric | Value |
| --- | ---: |
| parse_success_rate | 1.0000 |
| ocr_trigger_rate | 0.2000 |
| parse_duration_ms_avg | 1798.0000 |
| clean_duration_ms_avg | 340.0000 |
| quality_score_avg | 0.8360 |

## Text Metrics

| Metric | Value |
| --- | ---: |
| field_exact_match_rate | 1.0000 |
| required_phrase_hit_rate | 1.0000 |

## Structure Metrics

| Metric | Value |
| --- | ---: |
| title_hierarchy | 0.8880 |
| list | 0.3680 |
| table | 0.1760 |
| image | 0.1620 |
| link | 0.3420 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| process_metrics.clean_duration_ms_avg | 340.0000 | 420.0000 | -80.0000 | improved |
| process_metrics.ocr_trigger_rate | 0.2000 | 0.3400 | -0.1400 | improved |
| process_metrics.parse_duration_ms_avg | 1798.0000 | 1840.0000 | -42.0000 | improved |
| process_metrics.parse_success_rate | 1.0000 | 0.9300 | 0.0700 | improved |
| process_metrics.quality_score_avg | 0.8360 | 0.8400 | -0.0040 | regressed |
| structure_metrics.image | 0.1620 | 0.7400 | -0.5780 | regressed |
| structure_metrics.link | 0.3420 | 0.8100 | -0.4680 | regressed |
| structure_metrics.list | 0.3680 | 0.8300 | -0.4620 | regressed |
| structure_metrics.table | 0.1760 | 0.7800 | -0.6040 | regressed |
| structure_metrics.title_hierarchy | 0.8880 | 0.9100 | -0.0220 | regressed |
| text_metrics.field_exact_match_rate | 1.0000 | 0.8800 | 0.1200 | improved |
| text_metrics.required_phrase_hit_rate | 1.0000 | 0.8600 | 0.1400 | improved |
