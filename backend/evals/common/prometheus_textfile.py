from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from backend.evals.common.reporting import extract_numeric_metrics


def write_prometheus_textfile(
    path: str | None,
    *,
    benchmark: str,
    payload: Mapping[str, Any],
) -> None:
    if not path:
        return
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HELP notebooklm_benchmark_metric Offline benchmark metric exported from NotebookLM eval runners.",
        "# TYPE notebooklm_benchmark_metric gauge",
    ]
    for metric_name, metric_value in sorted(extract_numeric_metrics(payload).items()):
        if metric_name in {"cases", "k"}:
            continue
        group, name = _split_metric_name(metric_name)
        lines.append(
            'notebooklm_benchmark_metric{benchmark="%s",metric_group="%s",metric_name="%s"} %s'
            % (benchmark, group, name, _format_value(metric_value))
        )

    if "cases" in payload:
        lines.extend(
            [
                "# HELP notebooklm_benchmark_cases Number of cases covered by the benchmark report.",
                "# TYPE notebooklm_benchmark_cases gauge",
                f'notebooklm_benchmark_cases{{benchmark="{benchmark}"}} {_format_value(float(payload["cases"]))}',
            ]
        )
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _split_metric_name(metric_name: str) -> tuple[str, str]:
    if "." not in metric_name:
        return "summary", metric_name
    group, name = metric_name.rsplit(".", 1)
    return group, name


def _format_value(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
