# NotebookLM RAG Benchmark

## Summary

- **benchmark**: rag
- **generated_at**: 2026-03-13T03:10:42.704730+00:00
- **cases**: 4
- **note**: Ragas metrics can be merged into this runner via --ragas-metrics.

## Metadata

- **dataset**: backend/evals/datasets/rag_qa/demo-rag-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/rag-demo.jsonl

## Retrieval Metrics

| Metric | Value |
| --- | ---: |
| context_precision | 1.0000 |
| context_recall | 0.9167 |
| hit_rate | 1.0000 |

## Answer Metrics

| Metric | Value |
| --- | ---: |
| answer_relevance_rouge_l | 0.7141 |
| completeness_phrase_hit_rate | 1.0000 |

## Citation Metrics

| Metric | Value |
| --- | ---: |
| citation_coverage_rate | 1.0000 |
| citation_correct_rate | 1.0000 |
| unsupported_assertion_rate | 0.0000 |

## Ragas Metrics

| Metric | Value |
| --- | ---: |
| context_precision | 0.8125 |
| context_recall | 0.7875 |
| faithfulness | 0.8350 |
| answer_relevancy | 0.8075 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| answer_metrics.answer_relevance_rouge_l | 0.7141 | 0.6900 | 0.0241 | improved |
| answer_metrics.completeness_phrase_hit_rate | 1.0000 | 0.8300 | 0.1700 | improved |
| citation_metrics.citation_correct_rate | 1.0000 | 0.8800 | 0.1200 | improved |
| citation_metrics.citation_coverage_rate | 1.0000 | 0.7400 | 0.2600 | improved |
| citation_metrics.unsupported_assertion_rate | 0.0000 | 0.0800 | -0.0800 | improved |
| ragas_metrics.answer_relevancy | 0.8075 | 0.8000 | 0.0075 | improved |
| ragas_metrics.context_precision | 0.8125 | 0.7900 | 0.0225 | improved |
| ragas_metrics.context_recall | 0.7875 | 0.7600 | 0.0275 | improved |
| ragas_metrics.faithfulness | 0.8350 | 0.8200 | 0.0150 | improved |
| retrieval_metrics.context_precision | 1.0000 | 0.8100 | 0.1900 | improved |
| retrieval_metrics.context_recall | 0.9167 | 0.7800 | 0.1367 | improved |
| retrieval_metrics.hit_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
