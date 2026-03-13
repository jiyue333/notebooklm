# NotebookLM RAG Benchmark

## Summary

- **benchmark**: rag
- **generated_at**: 2026-03-13T04:30:15.230902+00:00
- **cases**: 6
- **note**: Ragas metrics can be merged into this runner via --ragas-metrics.

## Metadata

- **dataset**: backend/evals/datasets/rag_qa/stable-rag-dataset.jsonl
- **predictions**: backend/evals/reports/predictions/rag-stable.jsonl

## Retrieval Metrics

| Metric | Value |
| --- | ---: |
| context_precision | 1.0000 |
| context_recall | 1.0000 |
| hit_rate | 1.0000 |

## Answer Metrics

| Metric | Value |
| --- | ---: |
| answer_relevance_rouge_l | 0.7845 |
| completeness_phrase_hit_rate | 0.9444 |

## Citation Metrics

| Metric | Value |
| --- | ---: |
| citation_coverage_rate | 1.0000 |
| citation_correct_rate | 1.0000 |
| unsupported_assertion_rate | 0.0000 |

## Ragas Metrics

| Metric | Value |
| --- | ---: |
| context_precision | 0.8600 |
| context_recall | 0.8400 |
| faithfulness | 0.8800 |
| answer_relevancy | 0.8700 |

## Baseline Comparison

| Metric | Current | Baseline | Delta | Status |
| --- | ---: | ---: | ---: | --- |
| answer_metrics.answer_relevance_rouge_l | 0.7845 | 0.7845 | 0.0000 | unchanged |
| answer_metrics.completeness_phrase_hit_rate | 0.9444 | 0.9444 | 0.0000 | unchanged |
| citation_metrics.citation_correct_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
| citation_metrics.citation_coverage_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
| citation_metrics.unsupported_assertion_rate | 0.0000 | 0.0000 | 0.0000 | unchanged |
| ragas_metrics.answer_relevancy | 0.8700 | 0.8700 | 0.0000 | unchanged |
| ragas_metrics.context_precision | 0.8600 | 0.8600 | 0.0000 | unchanged |
| ragas_metrics.context_recall | 0.8400 | 0.8400 | 0.0000 | unchanged |
| ragas_metrics.faithfulness | 0.8800 | 0.8800 | 0.0000 | unchanged |
| retrieval_metrics.context_precision | 1.0000 | 1.0000 | 0.0000 | unchanged |
| retrieval_metrics.context_recall | 1.0000 | 1.0000 | 0.0000 | unchanged |
| retrieval_metrics.hit_rate | 1.0000 | 1.0000 | 0.0000 | unchanged |
