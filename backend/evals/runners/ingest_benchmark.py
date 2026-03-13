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
from backend.evals.common.text_metrics import bertscore_f1_many, exact_match_rate, phrase_hit_rate


METRIC_DIRECTIONS = {
    "process_metrics.parse_success_rate": "higher",
    "process_metrics.ocr_trigger_rate": "lower",
    "process_metrics.parse_duration_ms_avg": "lower",
    "process_metrics.clean_duration_ms_avg": "lower",
    "process_metrics.quality_score_avg": "higher",
    "text_metrics.field_exact_match_rate": "higher",
    "text_metrics.required_phrase_hit_rate": "higher",
    "text_metrics.markdown_bert_score_f1": "higher",
    "structure_metrics.title_hierarchy": "higher",
    "structure_metrics.list": "higher",
    "structure_metrics.table": "higher",
    "structure_metrics.image": "higher",
    "structure_metrics.link": "higher",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ingest benchmark against parsed outputs")
    parser.add_argument("--dataset", required=True, help="Canonical ingest dataset JSONL")
    parser.add_argument("--results", required=True, help="Parsed result JSONL")
    add_common_output_args(parser)
    add_report_args(parser)
    parser.add_argument(
        "--with-bert-score",
        action="store_true",
        help="Compute BERTScore F1 when reference_markdown is available",
    )
    parser.add_argument(
        "--bert-model-type",
        default="bert-base-multilingual-cased",
        help="Model type passed to bert-score when enabled",
    )
    args = parser.parse_args()

    dataset = {row["case_id"]: row for row in read_jsonl(args.dataset)}
    results = {row["case_id"]: row for row in read_jsonl(args.results)}
    process = defaultdict(float)
    text = defaultdict(float)
    structure = defaultdict(float)
    count = 0
    bert_references: list[str] = []
    bert_predictions: list[str] = []

    for case_id, case in dataset.items():
        result = results.get(case_id, {})
        process["parse_success_rate"] += 1.0 if result.get("parse_success") else 0.0
        process["ocr_trigger_rate"] += 1.0 if result.get("ocr_triggered") else 0.0
        process["parse_duration_ms_avg"] += float(result.get("parse_duration_ms", 0) or 0)
        process["clean_duration_ms_avg"] += float(result.get("clean_duration_ms", 0) or 0)
        process["quality_score_avg"] += float(result.get("quality_score", 0) or 0)
        text["field_exact_match_rate"] += exact_match_rate(
            case.get("expected_fields", {}),
            result.get("extracted_fields", {}),
        )
        text["required_phrase_hit_rate"] += phrase_hit_rate(
            case.get("required_phrases", []),
            result.get("output_markdown", ""),
        )
        reference_markdown = str(case.get("reference_markdown", "")).strip()
        output_markdown = str(result.get("output_markdown", "")).strip()
        if args.with_bert_score and reference_markdown and output_markdown:
            bert_references.append(reference_markdown)
            bert_predictions.append(output_markdown)
        structure_scores = result.get("structure_scores", {})
        for structure_type in ("title_hierarchy", "list", "table", "image", "link"):
            structure[structure_type] += float(structure_scores.get(structure_type, 0) or 0)
        count += 1
    if args.with_bert_score and bert_references:
        bert_scores = bertscore_f1_many(
            bert_references,
            bert_predictions,
            model_type=args.bert_model_type,
        )
        text["markdown_bert_score_f1"] = sum(bert_scores) / max(len(bert_scores), 1)

    payload = build_benchmark_payload(
        benchmark="ingest",
        summary={"cases": count},
        metric_groups={
            "process_metrics": {
                key: round(value / max(count, 1), 4) for key, value in process.items()
            },
            "text_metrics": {
                key: round(value / max(count, 1), 4) for key, value in text.items()
            },
            "structure_metrics": {
                key: round(value / max(count, 1), 4) for key, value in structure.items()
            },
        },
        metadata={
            "dataset": args.dataset,
            "results": args.results,
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
        title="NotebookLM Ingest Benchmark",
        payload=payload,
        comparisons=comparisons,
    )
    write_prometheus_textfile(
        args.prometheus_output,
        benchmark="ingest",
        payload=payload,
    )
    regressions = find_regressions(comparisons)
    if args.fail_on_regression and regressions:
        metric_names = ", ".join(item["metric"] for item in regressions)
        raise SystemExit(f"ingest benchmark regressed against baseline: {metric_names}")


if __name__ == "__main__":
    main()
