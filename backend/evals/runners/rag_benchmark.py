from __future__ import annotations

import argparse
from collections import defaultdict

from backend.evals.common.cli import add_common_output_args, add_report_args, write_json
from backend.evals.common.jsonl import read_jsonl
from backend.evals.common.prometheus_textfile import write_prometheus_textfile
from backend.evals.common.ragas_eval import run_ragas_evaluation
from backend.evals.common.reporting import (
    build_benchmark_payload,
    compare_against_baseline,
    find_regressions,
    load_json,
    write_markdown_report,
)
from backend.evals.common.text_metrics import phrase_hit_rate, rouge_l_f1


METRIC_DIRECTIONS = {
    "retrieval_metrics.context_precision": "higher",
    "retrieval_metrics.context_recall": "higher",
    "retrieval_metrics.hit_rate": "higher",
    "answer_metrics.answer_relevance_rouge_l": "higher",
    "answer_metrics.completeness_phrase_hit_rate": "higher",
    "citation_metrics.citation_coverage_rate": "higher",
    "citation_metrics.citation_correct_rate": "higher",
    "citation_metrics.unsupported_assertion_rate": "lower",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run RAG QA benchmark")
    parser.add_argument("--dataset", required=True, help="Canonical RAG dataset JSONL")
    parser.add_argument("--predictions", required=True, help="RAG predictions JSONL")
    add_common_output_args(parser)
    add_report_args(parser)
    parser.add_argument(
        "--ragas-metrics",
        help="Optional JSON file with external Ragas metrics to merge into the report",
    )
    parser.add_argument(
        "--with-ragas",
        action="store_true",
        help="Run Ragas directly when optional eval dependencies and API credentials are available",
    )
    parser.add_argument("--ragas-api-key", help="Optional API key override for Ragas judge model")
    parser.add_argument("--ragas-base-url", help="Optional API base URL override for Ragas judge model")
    parser.add_argument("--ragas-model", help="Optional judge model name override for Ragas")
    parser.add_argument("--ragas-embedding-model", help="Optional embedding model name override for Ragas")
    args = parser.parse_args()

    dataset = {row["case_id"]: row for row in read_jsonl(args.dataset)}
    predictions = {row["case_id"]: row for row in read_jsonl(args.predictions)}
    retrieval_metrics = defaultdict(float)
    answer_metrics = defaultdict(float)
    citation_metrics = defaultdict(float)
    count = 0

    for case_id, case in dataset.items():
        prediction = predictions.get(case_id, {})
        retrieved = set(prediction.get("retrieved_context_ids", []))
        expected = set(case.get("expected_context_ids", []))
        acceptable = set(case.get("acceptable_context_ids", []))
        citation_ids = set(prediction.get("citation_ids", []))
        expected_citations = set(case.get("expected_citation_ids", []))
        answer = str(prediction.get("answer", "")).strip()
        reference_answer = case.get("reference_answer", "")

        relevant_pool = expected | acceptable
        retrieval_metrics["context_precision"] += len(retrieved & relevant_pool) / max(len(retrieved), 1)
        retrieval_metrics["context_recall"] += len(retrieved & expected) / max(len(expected), 1)
        retrieval_metrics["hit_rate"] += 1.0 if retrieved & expected else 0.0
        answer_metrics["answer_relevance_rouge_l"] += rouge_l_f1(reference_answer, answer)
        answer_metrics["completeness_phrase_hit_rate"] += phrase_hit_rate(case.get("required_phrases", []), answer)
        citation_metrics["citation_coverage_rate"] += len(citation_ids & expected_citations) / max(len(expected_citations), 1)
        citation_metrics["citation_correct_rate"] += len(citation_ids & expected_citations) / max(len(citation_ids), 1)
        citation_metrics["unsupported_assertion_rate"] += 0.0 if citation_ids or not answer else 1.0
        count += 1

    payload = build_benchmark_payload(
        benchmark="rag",
        summary={"cases": count},
        metric_groups={
            "retrieval_metrics": {
                key: round(value / max(count, 1), 4) for key, value in retrieval_metrics.items()
            },
            "answer_metrics": {
                key: round(value / max(count, 1), 4) for key, value in answer_metrics.items()
            },
            "citation_metrics": {
                key: round(value / max(count, 1), 4) for key, value in citation_metrics.items()
            },
        },
        note="Ragas metrics can be merged into this runner via --ragas-metrics.",
        metadata={
            "dataset": args.dataset,
            "predictions": args.predictions,
        },
    )
    ragas_payload = load_json(args.ragas_metrics)
    if ragas_payload:
        payload["ragas_metrics"] = ragas_payload.get("metrics", ragas_payload)
    elif args.with_ragas:
        payload["ragas_metrics"] = run_ragas_evaluation(
            dataset_rows=list(dataset.values()),
            prediction_rows=list(predictions.values()),
            api_key=args.ragas_api_key,
            base_url=args.ragas_base_url,
            model=args.ragas_model,
            embedding_model=args.ragas_embedding_model,
        )
    baseline_payload = load_json(args.baseline)
    comparisons = compare_against_baseline(payload, baseline_payload, METRIC_DIRECTIONS)
    if comparisons:
        payload["baseline_comparison"] = comparisons
    write_json(args.output, payload)
    write_markdown_report(
        args.markdown_output,
        title="NotebookLM RAG Benchmark",
        payload=payload,
        comparisons=comparisons,
    )
    write_prometheus_textfile(
        args.prometheus_output,
        benchmark="rag",
        payload=payload,
    )
    regressions = find_regressions(comparisons)
    if args.fail_on_regression and regressions:
        metric_names = ", ".join(item["metric"] for item in regressions)
        raise SystemExit(f"rag benchmark regressed against baseline: {metric_names}")


if __name__ == "__main__":
    main()
