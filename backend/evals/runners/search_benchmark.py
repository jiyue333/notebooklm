from __future__ import annotations

import argparse
from collections import defaultdict

from backend.evals.common.cli import add_common_output_args, add_report_args, write_json
from backend.evals.common.jsonl import read_jsonl
from backend.evals.common.prometheus_textfile import write_prometheus_textfile
from backend.evals.common.ranking import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from backend.evals.common.reporting import (
    build_benchmark_payload,
    compare_against_baseline,
    find_regressions,
    load_json,
    write_markdown_report,
)


METRIC_DIRECTIONS = {
    "metrics.recall_at_k": "higher",
    "metrics.precision_at_k": "higher",
    "metrics.mrr": "higher",
    "metrics.ndcg_at_k": "higher",
    "metrics.freshness_satisfaction_rate": "higher",
    "metrics.authority_hit_rate": "higher",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run search benchmark against dataset and predictions")
    parser.add_argument("--dataset", required=True, help="Canonical search dataset JSONL")
    parser.add_argument("--predictions", required=True, help="Predictions JSONL")
    parser.add_argument("--k", type=int, default=5, help="Cutoff for ranking metrics")
    add_common_output_args(parser)
    add_report_args(parser)
    args = parser.parse_args()

    dataset = {row["case_id"]: row for row in read_jsonl(args.dataset)}
    predictions = {row["case_id"]: row for row in read_jsonl(args.predictions)}

    totals = defaultdict(float)
    count = 0
    for case_id, case in dataset.items():
        prediction = predictions.get(case_id, {})
        ranked_doc_ids = prediction.get("ranked_doc_ids", [])
        relevant = set(case.get("expected_docs", []))
        graded = {doc_id: 1.0 for doc_id in case.get("expected_docs", [])}
        graded.update({doc_id: 0.5 for doc_id in case.get("acceptable_docs", [])})
        totals["recall_at_k"] += recall_at_k(ranked_doc_ids, relevant, args.k)
        totals["precision_at_k"] += precision_at_k(ranked_doc_ids, relevant, args.k)
        totals["mrr"] += reciprocal_rank(ranked_doc_ids, relevant)
        totals["ndcg_at_k"] += ndcg_at_k(ranked_doc_ids, graded, args.k)
        totals["freshness_satisfaction_rate"] += 1.0 if prediction.get("freshness_satisfied") else 0.0
        totals["authority_hit_rate"] += 1.0 if prediction.get("authority_hit") else 0.0
        count += 1

    payload = build_benchmark_payload(
        benchmark="search",
        summary={"cases": count, "k": args.k},
        metric_groups={
            "metrics": {key: round(value / max(count, 1), 4) for key, value in totals.items()},
        },
        metadata={
            "dataset": args.dataset,
            "predictions": args.predictions,
        },
    )
    baseline_payload = load_json(args.baseline)
    comparisons = compare_against_baseline(payload, baseline_payload, METRIC_DIRECTIONS)
    if comparisons:
        payload["baseline_comparison"] = comparisons
    write_json(args.output, payload)
    write_markdown_report(
        args.markdown_output,
        title="NotebookLM Search Benchmark",
        payload=payload,
        comparisons=comparisons,
    )
    write_prometheus_textfile(
        args.prometheus_output,
        benchmark="search",
        payload=payload,
    )
    regressions = find_regressions(comparisons)
    if args.fail_on_regression and regressions:
        metric_names = ", ".join(item["metric"] for item in regressions)
        raise SystemExit(f"search benchmark regressed against baseline: {metric_names}")


if __name__ == "__main__":
    main()
