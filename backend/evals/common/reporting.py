from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping


MetricDirections = Mapping[str, str]
IGNORED_NUMERIC_KEYS = {"cases", "k"}


def load_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    file_path = Path(path)
    if not file_path.exists():
        return None
    return json.loads(file_path.read_text(encoding="utf-8"))


def build_benchmark_payload(
    *,
    benchmark: str,
    summary: dict[str, Any],
    metric_groups: dict[str, dict[str, float]],
    note: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "benchmark": benchmark,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **summary,
    }
    payload.update(metric_groups)
    if metadata:
        payload["metadata"] = metadata
    if note:
        payload["note"] = note
    return payload


def extract_numeric_metrics(payload: Mapping[str, Any], prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    for key, value in payload.items():
        metric_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            flattened.update(extract_numeric_metrics(value, metric_key))
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            flattened[metric_key] = float(value)
    return flattened


def compare_against_baseline(
    payload: Mapping[str, Any],
    baseline_payload: Mapping[str, Any] | None,
    directions: MetricDirections,
) -> list[dict[str, Any]]:
    if not baseline_payload:
        return []
    current_metrics = extract_numeric_metrics(payload)
    baseline_metrics = extract_numeric_metrics(baseline_payload)
    comparisons: list[dict[str, Any]] = []
    for metric_name, current_value in sorted(current_metrics.items()):
        if metric_name in IGNORED_NUMERIC_KEYS:
            continue
        if metric_name not in baseline_metrics:
            continue
        baseline_value = baseline_metrics[metric_name]
        delta = round(current_value - baseline_value, 4)
        direction = directions.get(metric_name, "higher")
        if delta == 0:
            status = "unchanged"
        elif direction == "lower":
            status = "improved" if delta < 0 else "regressed"
        else:
            status = "improved" if delta > 0 else "regressed"
        comparisons.append(
            {
                "metric": metric_name,
                "current": round(current_value, 4),
                "baseline": round(baseline_value, 4),
                "delta": delta,
                "status": status,
            }
        )
    return comparisons


def find_regressions(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in comparisons if item.get("status") == "regressed"]


def write_markdown_report(
    path: str | None,
    *,
    title: str,
    payload: Mapping[str, Any],
    comparisons: list[dict[str, Any]] | None = None,
) -> None:
    if not path:
        return
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {title}", ""]

    summary_keys = ("benchmark", "generated_at", "cases", "k", "note")
    summary_rows = [(key, payload[key]) for key in summary_keys if key in payload]
    if summary_rows:
        lines.append("## Summary")
        lines.append("")
        for key, value in summary_rows:
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    if "metadata" in payload and isinstance(payload["metadata"], Mapping):
        lines.append("## Metadata")
        lines.append("")
        for key, value in payload["metadata"].items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")

    for key, value in payload.items():
        if key in {"benchmark", "generated_at", "cases", "k", "note", "metadata"}:
            continue
        if not isinstance(value, Mapping):
            continue
        lines.append(f"## {key.replace('_', ' ').title()}")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("| --- | ---: |")
        for metric_name, metric_value in value.items():
            if isinstance(metric_value, (int, float)) and not isinstance(metric_value, bool):
                lines.append(f"| {metric_name} | {metric_value:.4f} |")
            else:
                lines.append(f"| {metric_name} | {metric_value} |")
        lines.append("")

    if comparisons:
        lines.append("## Baseline Comparison")
        lines.append("")
        lines.append("| Metric | Current | Baseline | Delta | Status |")
        lines.append("| --- | ---: | ---: | ---: | --- |")
        for item in comparisons:
            lines.append(
                f"| {item['metric']} | {item['current']:.4f} | {item['baseline']:.4f} | "
                f"{item['delta']:.4f} | {item['status']} |"
            )
        lines.append("")

    file_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
