# NotebookLM Ingest Benchmark

## Summary

- **benchmark**: ingest
- **generated_at**: 2026-03-13T04:30:15.057874+00:00
- **cases**: 8

## Metadata

- **dataset**: backend/evals/datasets/ingest/stable-ingest-dataset.jsonl
- **results**: backend/evals/reports/predictions/ingest-stable.jsonl
- **with_bert_score**: False

## Process Metrics

| Metric | Value |
| --- | ---: |
| parse_success_rate | 1.0000 |
| ocr_trigger_rate | 0.1250 |
| parse_duration_ms_avg | 1271.8750 |
| clean_duration_ms_avg | 255.0000 |
| quality_score_avg | 0.8738 |

## Text Metrics

| Metric | Value |
| --- | ---: |
| field_exact_match_rate | 1.0000 |
| required_phrase_hit_rate | 1.0000 |

## Structure Metrics

| Metric | Value |
| --- | ---: |
| title_hierarchy | 0.9175 |
| list | 0.4600 |
| table | 0.1125 |
| image | 0.2075 |
| link | 0.3350 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| process_metrics.clean_duration_ms_avg | 255.0000 | 255.0000 | 0.0000 | unchanged |
| process_metrics.ocr_trigger_rate | 0.1250 | 0.1250 | 0.0000 | unchanged |
| process_metrics.parse_duration_ms_avg | 1271.8750 | 1271.8750 | 0.0000 | unchanged |
| process_metrics.parse_success_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
| process_metrics.quality_score_avg | 0.8738 | 0.8738 | 0.0000 | unchanged |
| structure_metrics.image | 0.2075 | 0.2075 | 0.0000 | unchanged |
| structure_metrics.link | 0.3350 | 0.3350 | 0.0000 | unchanged |
| structure_metrics.list | 0.4600 | 0.4600 | 0.0000 | unchanged |
| structure_metrics.table | 0.1125 | 0.1125 | 0.0000 | unchanged |
| structure_metrics.title_hierarchy | 0.9175 | 0.9175 | 0.0000 | unchanged |
| text_metrics.field_exact_match_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
| text_metrics.required_phrase_hit_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
