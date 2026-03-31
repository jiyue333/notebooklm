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


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


def build_markdown(report: dict[str, Any]) -> str:
    if report.get("pipeline") == "all":
        return _build_all_markdown(report)
    return _build_pipeline_markdown(report)


def _build_all_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Eval Report - {report['bench_run_id']}",
        "",
        f"- pipeline: all",
        f"- profile: {report.get('profile')}",
        f"- app_version: {report.get('app_version')}",
        "",
        "| Pipeline | Success Rate | Judge Avg | P95 (ms) | Run ID |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for item in report.get("pipelines") or []:
        s = item.get("summary") or {}
        q = s.get("quality") or {}
        lat = s.get("latency_ms") or {}
        lines.append(
            f"| {item.get('pipeline')} | {s.get('success_rate', 0):.4f} | "
            f"{q.get('avg_score', 0):.4f} | {lat.get('p95', 0):.2f} | "
            f"{item.get('bench_run_id')} |"
        )
    return "\n".join(lines)


def _build_pipeline_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    quality = summary.get("quality") or {}
    latency = summary.get("latency_ms") or {}
    lines = [
        f"# Eval Report - {report['bench_run_id']}",
        "",
        f"- pipeline: {report.get('pipeline')}",
        f"- profile: {report.get('profile')}",
        f"- app_version: {report.get('app_version')}",
        f"- prompt_version: {report.get('prompt_version')}",
        f"- generated_at: {report.get('generated_at')}",
        "",
        "## Overview",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Total Cases | {summary.get('total_cases')} |",
        f"| Repeat / Case | {summary.get('repeat_per_case')} |",
        f"| Total Attempts | {summary.get('total_attempts')} |",
        f"| Success Rate | {summary.get('success_rate')} |",
        f"| Judge Avg | {quality.get('avg_score')} |",
        f"| Judge Pass Rate | {quality.get('pass_rate')} |",
        f"| Latency P95 (ms) | {latency.get('p95', 0):.2f} |",
        "",
    ]
    warnings = quality.get("warnings") or []
    if warnings:
        lines.extend(["### Warnings", ""])
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")
    for case in report.get("cases") or []:
        lines.extend(_case_markdown(case))
    failures = report.get("failures") or []
    if failures:
        lines.extend([
            "---",
            "",
            "## Failure Summary",
            "",
            "| Case | Repeat | Judge Reason | Error |",
            "| --- | ---: | --- | --- |",
        ])
        for f in failures:
            err = str(f.get("error") or "")[:100]
            lines.append(
                f"| {f.get('case_id')} | {f.get('repeat_index')} | "
                f"{f.get('judge_reason') or ''} | {err} |"
            )
        lines.append("")
    return "\n".join(lines)


def _case_markdown(case: dict[str, Any]) -> list[str]:
    agg = case.get("aggregate") or {}
    js = agg.get("judge_score") or {}
    lat = agg.get("latency_ms") or {}
    stages = agg.get("stage_metrics") or {}
    subs = agg.get("subscores") or {}
    inp = case.get("input") or {}
    pr = float(agg.get("judge_pass_rate", 0))
    status = "PASS" if pr >= 1.0 else ("PARTIAL" if pr > 0 else "FAIL")
    lines = [
        "---",
        "",
        f"## Case: {case.get('case_id')} [{status}]",
        "",
    ]
    for k, v in inp.items():
        vs = str(v)
        if len(vs) > 120:
            vs = vs[:120] + "..."
        lines.append(f"- **{k}**: {vs}")
    lines.append("")
    lines.append(
        f"Score avg={js.get('avg', 0):.4f} | pass_rate={pr:.2%} | "
        f"attempts={agg.get('attempts', 0)} | "
        f"latency avg={lat.get('avg', 0):.0f}ms p95={lat.get('p95', 0):.0f}ms"
    )
    lines.append("")
    if subs:
        lines.extend([
            "### Subscores",
            "",
            "| Dimension | Avg | Min | Max |",
            "| --- | ---: | ---: | ---: |",
        ])
        for k, s in subs.items():
            lines.append(
                f"| {k} | {s.get('avg', 0):.4f} | "
                f"{s.get('min', 0):.4f} | {s.get('max', 0):.4f} |"
            )
        lines.append("")
    if stages:
        lines.extend([
            "### Stage Latency",
            "",
            "| Stage | Avg (ms) | P50 (ms) | P95 (ms) | Samples |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        for stage, s in stages.items():
            lines.append(
                f"| {stage} | {s.get('avg', 0):.2f} | "
                f"{s.get('p50', 0):.2f} | {s.get('p95', 0):.2f} | "
                f"{s.get('samples', 0)} |"
            )
        lines.append("")
    attempt_details = agg.get("attempt_details") or []
    if attempt_details:
        lines.extend([
            "### Attempts",
            "",
            "| # | Status | Score | Latency (ms) | Error / Reason |",
            "| ---: | --- | ---: | ---: | --- |",
        ])
        for d in attempt_details:
            if d.get("error"):
                st_label = "ERROR"
                reason = str(d["error"])[:120]
            elif not d.get("judge_pass"):
                st_label = "FAIL"
                reason = str(d.get("judge_reason") or "")[:120]
            else:
                st_label = "PASS"
                reason = ""
            lines.append(
                f"| {d.get('repeat_index', '')} | {st_label} | "
                f"{d.get('judge_score', 0):.4f} | "
                f"{d.get('duration_ms', 0):.0f} | {reason} |"
            )
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def build_html(report: dict[str, Any]) -> str:
    if report.get("pipeline") == "all":
        return _build_all_html(report)
    return _build_pipeline_html(report)


def _build_all_html(report: dict[str, Any]) -> str:
    tab_links: list[str] = []
    cards: list[str] = []
    for item in report.get("pipelines") or []:
        s = item.get("summary") or {}
        q = s.get("quality") or {}
        lat = s.get("latency_ms") or {}
        ls_data = item.get("langsmith") or {}
        exp = ls_data.get("experiment") or {}
        exp_url = exp.get("url")
        cards.append(f"""
        <section class="panel">
          <h3>{html.escape(str(item.get("pipeline") or ""))}</h3>
          <div class="metrics-grid">
            <div class="metric"><span>Success Rate</span><strong>{float(s.get("success_rate", 0.0)):.4f}</strong></div>
            <div class="metric"><span>Judge Avg</span><strong>{float(q.get("avg_score", 0.0)):.4f}</strong></div>
            <div class="metric"><span>P95 (ms)</span><strong>{float(lat.get("p95", 0.0)):.2f}</strong></div>
            <div class="metric"><span>Run ID</span><strong>{html.escape(str(item.get("bench_run_id") or ""))}</strong></div>
          </div>
          {"<a class='link' href='" + html.escape(str(exp_url)) + "' target='_blank' rel='noreferrer'>Open LangSmith</a>" if exp_url else ""}
        </section>""")
        tab_links.append(
            f"<a class='tab-link' href='../{html.escape(str(item.get('bench_run_id') or ''))}/report.html'>"
            f"{html.escape(str(item.get('pipeline') or ''))}</a>"
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
    <h2>Pipelines</h2>
    <div class="tab-wrap">{''.join(tab_links)}</div>
  </section>
  {''.join(cards)}
</body>
</html>"""


def _build_pipeline_html(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    quality = summary.get("quality") or {}
    latency = summary.get("latency_ms") or {}
    ttfb = summary.get("ttfb_ms") or {}
    token_cost = summary.get("token_cost") or {}
    baseline = report.get("baseline_diff") or {}
    langsmith = report.get("langsmith") or {}
    experiment = langsmith.get("experiment") or {}
    experiment_url = experiment.get("url")
    warnings = quality.get("warnings") or []

    warning_html = ""
    if warnings:
        items = "".join(f"<li>{html.escape(str(w))}</li>" for w in warnings)
        warning_html = f"""
  <section class="panel warning-panel">
    <h3>Data Quality Warnings</h3>
    <ul class="warning-list">{items}</ul>
  </section>"""

    baseline_html = ""
    if baseline.get("available"):
        m = baseline.get("metrics") or {}
        baseline_html = f"""
  <section class="panel">
    <h3>Baseline Diff</h3>
    <p>vs <code>{html.escape(str(baseline.get('bench_run_id')))}</code></p>
    <div class="metrics-grid">
      <div class="metric"><span>Success Δ</span><strong>{float(m.get('success_rate_delta', 0.0)):.4f}</strong></div>
      <div class="metric"><span>P95 Δ (ms)</span><strong>{float(m.get('latency_p95_delta_ms', 0.0)):.2f}</strong></div>
      <div class="metric"><span>Judge Avg Δ</span><strong>{float(m.get('quality_avg_delta', 0.0)):.4f}</strong></div>
    </div>
  </section>"""

    case_panels = "\n".join(_case_panel_html(c) for c in (report.get("cases") or []))

    failures = report.get("failures") or []
    failure_html = ""
    if failures:
        f_rows = ""
        for f in failures:
            err = html.escape(str(f.get("error") or "")[:160])
            f_rows += (
                f"<tr><td>{html.escape(str(f.get('case_id')))}</td>"
                f"<td>{f.get('repeat_index')}</td>"
                f"<td>{html.escape(str(f.get('judge_reason') or ''))}</td>"
                f"<td class='reason-cell'>{err}</td>"
                f"<td>{_safe_link(f.get('langsmith_url'))}</td></tr>"
            )
        failure_html = f"""
  <section class="panel warning-panel">
    <h2>Failure Summary ({len(failures)})</h2>
    <table>
      <thead><tr><th>Case</th><th>#</th><th>Judge Reason</th><th>Error</th><th>Trace</th></tr></thead>
      <tbody>{f_rows}</tbody>
    </table>
  </section>"""

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
    <p>bench_run_id: <code>{html.escape(str(report.get("bench_run_id")))}</code> ·
       pipeline: <code>{html.escape(str(report.get("pipeline")))}</code> ·
       profile: <code>{html.escape(str(report.get("profile")))}</code></p>
    <p>app_version: <code>{html.escape(str(report.get("app_version")))}</code> ·
       prompt_version: <code>{html.escape(str(report.get("prompt_version")))}</code></p>
    {"<a class='link' href='" + html.escape(str(experiment_url)) + "' target='_blank' rel='noreferrer'>Open LangSmith Experiment</a>" if experiment_url else ""}
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
  </section>
  {baseline_html}
  {warning_html}

  {failure_html}

  <h2 class="section-title">Case Details</h2>
  {case_panels}
</body>
</html>"""


def _case_panel_html(case: dict[str, Any]) -> str:
    agg = case.get("aggregate") or {}
    js = agg.get("judge_score") or {}
    lat = agg.get("latency_ms") or {}
    ttfb = agg.get("ttfb_ms") or {}
    stages = agg.get("stage_metrics") or {}
    subs = agg.get("subscores") or {}
    inp = case.get("input") or {}

    pr = float(agg.get("judge_pass_rate", 0))
    if pr >= 1.0:
        sc, st = "pass", "PASS"
    elif pr > 0:
        sc, st = "partial", "PARTIAL"
    else:
        sc, st = "fail", "FAIL"

    input_parts = []
    for k, v in inp.items():
        vs = html.escape(str(v))
        if len(vs) > 160:
            vs = vs[:160] + "…"
        input_parts.append(f"<span class='input-item'><em>{html.escape(k)}</em>: {vs}</span>")
    input_html = f"<div class='case-input'>{''.join(input_parts)}</div>" if input_parts else ""

    sub_rows = ""
    if subs:
        for k, s in subs.items():
            a = float(s.get("avg", 0))
            sub_rows += (
                f"<tr><td>{html.escape(k)}</td><td>{a:.4f}</td>"
                f"<td>{float(s.get('min', 0)):.4f}</td>"
                f"<td>{float(s.get('max', 0)):.4f}</td>"
                f"<td>{_bar_cell(a, 1.0)}</td></tr>"
            )
    sub_html = f"""
      <div class="case-section">
        <h4>Subscores</h4>
        <table>
          <thead><tr><th>Dimension</th><th>Avg</th><th>Min</th><th>Max</th><th>Visual</th></tr></thead>
          <tbody>{sub_rows}</tbody>
        </table>
      </div>""" if sub_rows else ""

    stg_rows = ""
    if stages:
        mx = max((float((s or {}).get("p95", 0)) for s in stages.values()), default=1.0)
        for stage, s in stages.items():
            stg_rows += (
                f"<tr><td>{html.escape(stage)}</td>"
                f"<td>{s.get('avg', 0):.2f}</td><td>{s.get('p50', 0):.2f}</td>"
                f"<td>{s.get('p95', 0):.2f}</td><td>{s.get('samples', 0)}</td>"
                f"<td>{_bar_cell(float(s.get('p95', 0)), mx)}</td></tr>"
            )
    stg_html = f"""
      <div class="case-section">
        <h4>Stage Latency</h4>
        <table>
          <thead><tr><th>Stage</th><th>Avg (ms)</th><th>P50 (ms)</th><th>P95 (ms)</th><th>Samples</th><th>P95 Visual</th></tr></thead>
          <tbody>{stg_rows}</tbody>
        </table>
      </div>""" if stg_rows else ""

    attempt_details = agg.get("attempt_details") or []
    att_rows = ""
    if attempt_details:
        for d in attempt_details:
            if d.get("error"):
                att_st = "<span class='status-badge fail'>ERROR</span>"
                att_reason = html.escape(str(d["error"])[:160])
            elif not d.get("judge_pass"):
                att_st = "<span class='status-badge fail'>FAIL</span>"
                att_reason = html.escape(str(d.get("judge_reason") or "")[:160])
            else:
                att_st = "<span class='status-badge pass'>PASS</span>"
                att_reason = ""
            att_rows += (
                f"<tr><td>{d.get('repeat_index', '')}</td><td>{att_st}</td>"
                f"<td>{d.get('judge_score', 0):.4f}</td>"
                f"<td>{d.get('duration_ms', 0):.0f}</td>"
                f"<td class='reason-cell'>{att_reason}</td></tr>"
            )
    att_html = f"""
      <div class="case-section">
        <h4>Attempts</h4>
        <table>
          <thead><tr><th>#</th><th>Status</th><th>Score</th><th>Latency (ms)</th><th>Error / Reason</th></tr></thead>
          <tbody>{att_rows}</tbody>
        </table>
      </div>""" if att_rows else ""

    return f"""
  <section class="panel case-panel">
    <div class="case-header">
      <h3>{html.escape(str(case.get('case_id')))}</h3>
      <span class="status-badge {sc}">{st}</span>
    </div>
    {input_html}
    <div class="metrics-grid">
      <div class="metric"><span>Score Avg</span><strong>{float(js.get('avg', 0)):.4f}</strong></div>
      <div class="metric"><span>Pass Rate</span><strong>{pr:.2%}</strong></div>
      <div class="metric"><span>Attempts</span><strong>{int(agg.get('attempts', 0))}</strong></div>
      <div class="metric"><span>Latency Avg</span><strong>{float(lat.get('avg', 0)):.0f}ms</strong></div>
      <div class="metric"><span>Latency P95</span><strong>{float(lat.get('p95', 0)):.0f}ms</strong></div>
      <div class="metric"><span>TTFB Avg</span><strong>{float(ttfb.get('avg', 0)):.0f}ms</strong></div>
    </div>
    {sub_html}
    {stg_html}
    {att_html}
  </section>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_link(url: Any) -> str:
    if not url:
        return ""
    escaped = html.escape(str(url))
    return f"<a class='link' href='{escaped}' target='_blank' rel='noreferrer'>open</a>"


def _bar_cell(value: float, max_value: float) -> str:
    d = max(max_value, 1e-6)
    r = max(0.0, min(1.0, value / d))
    return (
        "<div class='bar-track'>"
        f"<span class='bar-fill' style='width:{r * 100:.2f}%'></span>"
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
      --warn: #ffc107;
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
    h4 { margin: 0 0 8px 0; font-size: 15px; color: #bdd1ff; }
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
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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
      top: 0; left: 0; bottom: 0;
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
    .warning-list li { margin: 6px 0; }
    .section-title {
      margin: 20px 0 12px 0;
      font-size: 22px;
    }
    .case-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 12px;
    }
    .case-header h3 { margin: 0; }
    .status-badge {
      padding: 4px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.5px;
    }
    .status-badge.pass {
      background: rgba(61, 214, 140, 0.15);
      color: var(--good);
      border: 1px solid rgba(61, 214, 140, 0.3);
    }
    .status-badge.partial {
      background: rgba(255, 193, 7, 0.15);
      color: var(--warn);
      border: 1px solid rgba(255, 193, 7, 0.3);
    }
    .status-badge.fail {
      background: rgba(255, 107, 107, 0.15);
      color: var(--bad);
      border: 1px solid rgba(255, 107, 107, 0.3);
    }
    .case-input {
      margin-bottom: 12px;
      padding: 10px 14px;
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid var(--panel-border);
      border-radius: 10px;
    }
    .input-item {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin: 2px 0;
      word-break: break-all;
    }
    .input-item em {
      font-style: normal;
      color: #bdd1ff;
      font-weight: 500;
    }
    .case-section { margin-top: 14px; }
    .reason-cell {
      font-size: 12px;
      color: var(--muted);
      max-width: 400px;
      word-break: break-word;
    }
    .error-info {
      margin-top: 10px;
      padding: 8px 12px;
      background: rgba(255, 107, 107, 0.08);
      border: 1px solid rgba(255, 107, 107, 0.2);
      border-radius: 8px;
      font-size: 13px;
      color: var(--bad);
    }
  </style>
"""
