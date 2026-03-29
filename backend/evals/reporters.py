from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_report_bundle(run_dir: Path, report: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (run_dir / "report.md").write_text(build_markdown(report))
    (run_dir / "report.html").write_text(build_html(report))


def build_markdown(report: dict[str, Any]) -> str:
    pipeline = report.get("pipeline")
    if pipeline == "all":
        lines = [
            f"# Eval Report - {report['bench_run_id']}",
            "",
            f"- pipeline: {pipeline}",
            f"- profile: {report.get('profile')}",
            f"- app_version: {report.get('app_version')}",
            "",
            "| pipeline | success_rate | quality_avg | p95(ms) | bench_run_id |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
        for item in report.get("pipelines") or []:
            summary = item.get("summary") or {}
            quality = summary.get("quality") or {}
            latency = summary.get("latency_ms") or {}
            lines.append(
                f"| {item.get('pipeline')} | {summary.get('success_rate', 0):.4f} | "
                f"{quality.get('avg_score', 0):.4f} | {latency.get('p95', 0):.2f} | "
                f"{item.get('bench_run_id')} |"
            )
        return "\n".join(lines)

    summary = report.get("summary") or {}
    quality = summary.get("quality") or {}
    lines = [
        f"# Eval Report - {report['bench_run_id']}",
        "",
        f"- pipeline: {report.get('pipeline')}",
        f"- profile: {report.get('profile')}",
        f"- app_version: {report.get('app_version')}",
        f"- prompt_version: {report.get('prompt_version')}",
        f"- generated_at: {report.get('generated_at')}",
        "",
        "## Summary",
        "",
        f"- total_cases: {summary.get('total_cases')}",
        f"- repeat_per_case: {summary.get('repeat_per_case')}",
        f"- total_attempts: {summary.get('total_attempts')}",
        f"- success_rate: {summary.get('success_rate')}",
        f"- latency_p95_ms: {(summary.get('latency_ms') or {}).get('p95')}",
        f"- judge_avg: {quality.get('avg_score')}",
        f"- judge_pass_rate: {quality.get('pass_rate')}",
        f"- data_quality_warnings: {', '.join((quality.get('warnings') or [])) or 'none'}",
        "",
        "## Stage Latency",
        "",
        "| stage | p50(ms) | p90(ms) | p95(ms) | samples |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for stage, stats in (report.get("stage_metrics") or {}).items():
        lines.append(
            f"| {stage} | {stats.get('p50', 0):.2f} | {stats.get('p90', 0):.2f} | "
            f"{stats.get('p95', 0):.2f} | {stats.get('samples', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Case Results",
            "",
            "| case_id | attempts | pass_rate | score_avg | latency_p95 | latest_error |",
            "| --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for case in report.get("cases") or []:
        agg = case.get("aggregate") or {}
        lines.append(
            f"| {case.get('case_id')} | {agg.get('attempts', 0)} | {agg.get('judge_pass_rate', 0):.4f} | "
            f"{(agg.get('judge_score') or {}).get('avg', 0):.4f} | "
            f"{(agg.get('latency_ms') or {}).get('p95', 0):.2f} | "
            f"{agg.get('latest_error') or ''} |"
        )
    return "\n".join(lines)


def build_html(report: dict[str, Any]) -> str:
    if report.get("pipeline") == "all":
        return _build_all_html(report)
    return _build_single_pipeline_html(report)


def _build_all_html(report: dict[str, Any]) -> str:
    tab_links: list[str] = []
    pipeline_cards = []
    for item in report.get("pipelines") or []:
        summary = item.get("summary") or {}
        quality = summary.get("quality") or {}
        latency = summary.get("latency_ms") or {}
        langsmith = item.get("langsmith") or {}
        experiment = langsmith.get("experiment") or {}
        experiment_url = experiment.get("url")
        pipeline_cards.append(
            f"""
            <section class="panel">
              <h3>{html.escape(str(item.get("pipeline") or ""))}</h3>
              <div class="metrics-grid">
                <div class="metric"><span>Success Rate</span><strong>{float(summary.get("success_rate", 0.0)):.4f}</strong></div>
                <div class="metric"><span>Judge Avg</span><strong>{float(quality.get("avg_score", 0.0)):.4f}</strong></div>
                <div class="metric"><span>P95 (ms)</span><strong>{float(latency.get("p95", 0.0)):.2f}</strong></div>
                <div class="metric"><span>Bench Run</span><strong>{html.escape(str(item.get("bench_run_id") or ""))}</strong></div>
              </div>
              {"<a class='link' href='" + html.escape(str(experiment_url)) + "' target='_blank' rel='noreferrer'>Open LangSmith Experiment</a>" if experiment_url else ""}
            </section>
            """
        )
        tab_links.append(
            f"<a class='tab-link' href='../{html.escape(str(item.get('bench_run_id') or ''))}/report.html'>{html.escape(str(item.get('pipeline') or ''))}</a>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Eval Report {html.escape(str(report.get("bench_run_id")))}</title>
  {_base_style()}
</head>
<body>
  <header>
    <h1>NotebookLM Eval Report</h1>
    <p>bench_run_id: <code>{html.escape(str(report.get("bench_run_id")))}</code> · pipeline: <code>all</code> · profile: <code>{html.escape(str(report.get("profile")))}</code></p>
  </header>
  <section class="panel">
    <h2>Pipeline Tabs</h2>
    <div class="tab-wrap">{''.join(tab_links)}</div>
  </section>
  {''.join(pipeline_cards)}
</body>
</html>
"""


def _build_single_pipeline_html(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    quality = summary.get("quality") or {}
    subscore_stats = quality.get("subscore_stats") or {}
    quality_warnings = quality.get("warnings") or []
    latency = summary.get("latency_ms") or {}
    ttfb = summary.get("ttfb_ms") or {}
    token_cost = summary.get("token_cost") or {}
    counters = summary.get("counters") or {}
    baseline = report.get("baseline_diff") or {}
    langsmith = report.get("langsmith") or {}
    experiment = langsmith.get("experiment") or {}
    experiment_url = experiment.get("url")

    stage_metrics = report.get("stage_metrics") or {}
    stage_p95_values = [float((stats or {}).get("p95", 0.0)) for stats in stage_metrics.values()]
    max_stage_p95 = max(stage_p95_values) if stage_p95_values else 1.0
    stage_rows = "".join(
        f"<tr><td>{html.escape(stage)}</td><td>{stats.get('p50', 0):.2f}</td><td>{stats.get('p90', 0):.2f}</td>"
        f"<td>{stats.get('p95', 0):.2f}</td><td>{stats.get('samples', 0)}</td><td>{_bar_cell(float(stats.get('p95', 0.0)), max_stage_p95)}</td></tr>"
        for stage, stats in stage_metrics.items()
    )

    subscore_rows = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{float(stats.get('avg', 0.0)):.4f}</td>"
        f"<td>{float(stats.get('stddev', 0.0)):.4f}</td><td>{float(stats.get('min', 0.0)):.4f}</td>"
        f"<td>{float(stats.get('max', 0.0)):.4f}</td><td>{float(stats.get('sat_high_rate', 0.0)):.2%}</td>"
        f"<td>{_bar_cell(float(stats.get('avg', 0.0)), 1.0)}</td></tr>"
        for key, stats in subscore_stats.items()
    )
    warning_list = (
        "<ul class='warning-list'>"
        + "".join(f"<li>{html.escape(str(item))}</li>" for item in quality_warnings)
        + "</ul>"
    ) if quality_warnings else "<p>No obvious data-quality warning.</p>"

    failure_rows = "".join(
        f"<tr><td>{html.escape(str(item.get('case_id')))}</td><td>{item.get('repeat_index')}</td>"
        f"<td>{html.escape(str(item.get('judge_reason') or ''))}</td>"
        f"<td>{html.escape(str(item.get('error') or ''))}</td>"
        f"<td>{_safe_link(item.get('langsmith_url'))}</td></tr>"
        for item in (report.get("failures") or [])
    )

    case_rows = "".join(_render_case_row(case) for case in (report.get("cases") or []))

    counter_badges = "".join(
        f"<span class='badge'>{html.escape(str(key))}: {int(value)}</span>"
        for key, value in sorted(counters.items())
    )

    baseline_html = "<p>baseline: none</p>"
    if baseline.get("available"):
        metrics = baseline.get("metrics") or {}
        baseline_html = (
            f"<p>baseline: <code>{html.escape(str(baseline.get('bench_run_id')))}</code></p>"
            f"<div class='metrics-grid'>"
            f"<div class='metric'><span>Success Δ</span><strong>{float(metrics.get('success_rate_delta', 0.0)):.4f}</strong></div>"
            f"<div class='metric'><span>Latency P95 Δ(ms)</span><strong>{float(metrics.get('latency_p95_delta_ms', 0.0)):.2f}</strong></div>"
            f"<div class='metric'><span>Judge Avg Δ</span><strong>{float(metrics.get('quality_avg_delta', 0.0)):.4f}</strong></div>"
            f"</div>"
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Eval Report {html.escape(str(report.get("bench_run_id")))}</title>
  {_base_style()}
</head>
<body>
  <header>
    <h1>NotebookLM Eval Report</h1>
    <p>bench_run_id: <code>{html.escape(str(report.get("bench_run_id")))}</code> · pipeline: <code>{html.escape(str(report.get("pipeline")))}</code> · profile: <code>{html.escape(str(report.get("profile")))}</code></p>
    <p>app_version: <code>{html.escape(str(report.get("app_version")))}</code> · prompt_version: <code>{html.escape(str(report.get("prompt_version")))}</code></p>
    {f"<a class='link' href='{html.escape(str(experiment_url))}' target='_blank' rel='noreferrer'>Open LangSmith Experiment</a>" if experiment_url else ""}
  </header>

  <section class="panel">
    <h2>Overview</h2>
    <div class="metrics-grid">
      <div class="metric"><span>Total Cases</span><strong>{int(summary.get("total_cases", 0))}</strong></div>
      <div class="metric"><span>Repeat / Case</span><strong>{int(summary.get("repeat_per_case", 0))}</strong></div>
      <div class="metric"><span>Total Attempts</span><strong>{int(summary.get("total_attempts", 0))}</strong></div>
      <div class="metric"><span>Success Rate</span><strong>{float(summary.get("success_rate", 0.0)):.4f}</strong></div>
      <div class="metric"><span>Judge Avg</span><strong>{float(quality.get("avg_score", 0.0)):.4f}</strong></div>
      <div class="metric"><span>Judge Pass Rate</span><strong>{float(quality.get("pass_rate", 0.0)):.4f}</strong></div>
      <div class="metric"><span>E2E P95 (ms)</span><strong>{float(latency.get("p95", 0.0)):.2f}</strong></div>
      <div class="metric"><span>TTFB P95 (ms)</span><strong>{float(ttfb.get("p95", 0.0)):.2f}</strong></div>
      <div class="metric"><span>Token Total</span><strong>{int(token_cost.get("total", 0))}</strong></div>
      <div class="metric"><span>Token Avg</span><strong>{float(token_cost.get("avg", 0.0)):.2f}</strong></div>
    </div>
    <div class="badge-wrap">{counter_badges}</div>
  </section>

  <section class="panel">
    <h2>Baseline Diff</h2>
    {baseline_html}
  </section>

  <section class="panel">
    <h2>Stage Latency (P50 / P90 / P95)</h2>
    <table>
      <thead><tr><th>Stage</th><th>P50</th><th>P90</th><th>P95</th><th>Samples</th><th>P95 Visual</th></tr></thead>
      <tbody>{stage_rows}</tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Judge Subscores</h2>
    <table>
      <thead><tr><th>Dimension</th><th>Avg</th><th>Std</th><th>Min</th><th>Max</th><th>Saturation(>=0.95)</th><th>Score Visual</th></tr></thead>
      <tbody>{subscore_rows}</tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Data Quality Diagnostics</h2>
    {warning_list}
  </section>

  <section class="panel">
    <h2>Failure Cases</h2>
    <table>
      <thead><tr><th>Case</th><th>Repeat</th><th>Reason</th><th>Error</th><th>LangSmith</th></tr></thead>
      <tbody>{failure_rows or "<tr><td colspan='5'>No failures</td></tr>"}</tbody>
    </table>
  </section>

  <section class="panel">
    <h2>Case Aggregates</h2>
    <table>
      <thead><tr><th>Case</th><th>Attempts</th><th>Pass Rate</th><th>Score Avg</th><th>Latency P95</th><th>Latest Error</th></tr></thead>
      <tbody>{case_rows}</tbody>
    </table>
  </section>
</body>
</html>
"""


def _render_case_row(case: dict[str, Any]) -> str:
    agg = case.get("aggregate") or {}
    judge_score = agg.get("judge_score") or {}
    latency = agg.get("latency_ms") or {}
    return (
        f"<tr><td>{html.escape(str(case.get('case_id')))}</td>"
        f"<td>{int(agg.get('attempts', 0))}</td>"
        f"<td>{float(agg.get('judge_pass_rate', 0.0)):.4f}</td>"
        f"<td>{float(judge_score.get('avg', 0.0)):.4f}</td>"
        f"<td>{float(latency.get('p95', 0.0)):.2f}</td>"
        f"<td>{html.escape(str(agg.get('latest_error') or ''))}</td></tr>"
    )


def _safe_link(url: Any) -> str:
    if not url:
        return ""
    escaped = html.escape(str(url))
    return f"<a class='link' href='{escaped}' target='_blank' rel='noreferrer'>open</a>"


def _bar_cell(value: float, max_value: float) -> str:
    denominator = max(max_value, 1e-6)
    ratio = max(0.0, min(1.0, value / denominator))
    return (
        "<div class='bar-track'>"
        f"<span class='bar-fill' style='width:{ratio * 100:.2f}%'></span>"
        f"<em>{value:.3f}</em>"
        "</div>"
    )


def _base_style() -> str:
    return """
  <style>
    :root {
      color-scheme: dark;
      --bg: #0b1220;
      --panel: #101b30;
      --panel-border: #20304d;
      --text: #d6e2ff;
      --muted: #8fa2c7;
      --accent: #6ea8fe;
      --good: #3dd68c;
      --bad: #ff6b6b;
    }
    * { box-sizing: border-box; }
    body {
      font-family: "Times New Roman", "Source Han Serif SC", serif;
      margin: 0;
      padding: 24px;
      background: linear-gradient(180deg, #0b1220 0%, #0a1020 100%);
      color: var(--text);
    }
    header { margin-bottom: 16px; }
    h1 { margin: 0 0 8px 0; font-size: 28px; }
    h2 { margin: 0 0 12px 0; font-size: 20px; }
    h3 { margin: 0 0 10px 0; font-size: 18px; }
    p { margin: 6px 0; color: var(--muted); }
    code {
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--panel-border);
      padding: 2px 6px;
      border-radius: 6px;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--panel-border);
      border-radius: 16px;
      padding: 16px;
      margin-bottom: 14px;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
      margin-top: 10px;
    }
    .metric {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid var(--panel-border);
      border-radius: 12px;
      padding: 10px 12px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }
    .metric strong {
      font-size: 18px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      border-bottom: 1px solid var(--panel-border);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: #bdd1ff;
      font-weight: 600;
      font-size: 13px;
    }
    .badge-wrap {
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--panel-border);
      background: rgba(255,255,255,0.04);
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      color: var(--muted);
    }
    .link {
      color: var(--accent);
      text-decoration: none;
      font-size: 14px;
    }
    .link:hover { text-decoration: underline; }
    .tab-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .tab-link {
      color: var(--text);
      text-decoration: none;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid var(--panel-border);
      background: rgba(255, 255, 255, 0.04);
      font-size: 13px;
    }
    .tab-link:hover {
      border-color: var(--accent);
      color: var(--accent);
    }
    .bar-track {
      width: 160px;
      height: 18px;
      border-radius: 999px;
      border: 1px solid var(--panel-border);
      background: rgba(255, 255, 255, 0.04);
      position: relative;
      overflow: hidden;
      display: inline-flex;
      align-items: center;
    }
    .bar-fill {
      position: absolute;
      top: 0;
      left: 0;
      bottom: 0;
      background: linear-gradient(90deg, #3d8bfd, #6ea8fe);
      opacity: 0.75;
    }
    .bar-track em {
      position: relative;
      z-index: 1;
      margin-left: 8px;
      font-style: normal;
      font-size: 11px;
      color: #dce7ff;
    }
    .warning-list {
      margin: 0;
      padding-left: 20px;
      color: #ffd6a1;
    }
    .warning-list li {
      margin: 6px 0;
    }
  </style>
"""
