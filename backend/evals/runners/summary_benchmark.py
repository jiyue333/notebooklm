from __future__ import annotations

import argparse
from collections import defaultdict

from backend.evals.common.cli import add_common_output_args, add_report_args, write_json
from backend.evals.common.jsonl import read_jsonl
from backend.evals.common.prometheus_textfile import write_prometheus_textfile
from backend.evals.common.reporting import (
    build_benchmark_payload,
    compare_against_baseline,
    find_regressions,
    load_json,
    write_markdown_report,
)
from backend.evals.common.text_metrics import bertscore_f1_many, phrase_hit_rate, rouge_1_f1, rouge_l_f1


METRIC_DIRECTIONS = {
    "metrics.rouge_1_f1": "higher",
    "metrics.rouge_l_f1": "higher",
    "metrics.required_phrase_hit_rate": "higher",
    "metrics.bert_score_f1": "higher",
    "metrics.compression_ratio": "lower",
    "metrics.summary_length_avg": "lower",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run summary benchmark")
    parser.add_argument("--dataset", required=True, help="Canonical summary dataset JSONL")
    parser.add_argument("--predictions", required=True, help="Summary predictions JSONL")
    add_common_output_args(parser)
    add_report_args(parser)
    parser.add_argument(
        "--with-bert-score",
        action="store_true",
        help="Compute BERTScore F1 for summaries",
    )
    parser.add_argument(
        "--bert-model-type",
        default="bert-base-multilingual-cased",
        help="Model type passed to bert-score when enabled",
    )
    args = parser.parse_args()

    dataset = {row["case_id"]: row for row in read_jsonl(args.dataset)}
    predictions = {row["case_id"]: row for row in read_jsonl(args.predictions)}
    metrics = defaultdict(float)
    count = 0
    bert_references: list[str] = []
    bert_predictions: list[str] = []

    for case_id, case in dataset.items():
        prediction = predictions.get(case_id, {})
        summary = str(prediction.get("summary", "")).strip()
        reference = case.get("reference_summary", "")
        metrics["rouge_1_f1"] += rouge_1_f1(reference, summary)
        metrics["rouge_l_f1"] += rouge_l_f1(reference, summary)
        metrics["required_phrase_hit_rate"] += phrase_hit_rate(case.get("required_phrases", []), summary)
        if case.get("source_chars"):
            metrics["compression_ratio"] += len(summary) / max(int(case["source_chars"]), 1)
        metrics["summary_length_avg"] += len(summary)
        if args.with_bert_score and reference and summary:
            bert_references.append(reference)
            bert_predictions.append(summary)
        count += 1
    if args.with_bert_score and bert_references:
        bert_scores = bertscore_f1_many(
            bert_references,
            bert_predictions,
            model_type=args.bert_model_type,
        )
        metrics["bert_score_f1"] = sum(bert_scores) / max(len(bert_scores), 1)

    payload = build_benchmark_payload(
        benchmark="summary",
        summary={"cases": count},
        metric_groups={
            "metrics": {key: round(value / max(count, 1), 4) for key, value in metrics.items()},
        },
        metadata={
            "dataset": args.dataset,
            "predictions": args.predictions,
            "with_bert_score": args.with_bert_score,
        },
    )
    baseline_payload = load_json(args.baseline)
    comparisons = compare_against_baseline(payload, baseline_payload, METRIC_DIRECTIONS)
    if comparisons:
        payload["baseline_comparison"] = comparisons
    write_json(args.output, payload)
    write_markdown_report(
        args.markdown_output,
        title="NotebookLM Summary Benchmark",
        payload=payload,
        comparisons=comparisons,
    )
    write_prometheus_textfile(
        args.prometheus_output,
        benchmark="summary",
        payload=payload,
    )
    regressions = find_regressions(comparisons)
    if args.fail_on_regression and regressions:
        metric_names = ", ".join(item["metric"] for item in regressions)
        raise SystemExit(f"summary benchmark regressed against baseline: {metric_names}")


if __name__ == "__main__":
    main()
