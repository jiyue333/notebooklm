from __future__ import annotations

import json
from pathlib import Path


def write_report_bundle(run_dir: Path, report: dict) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (run_dir / 'report.md').write_text(build_markdown(report))
    (run_dir / 'report.html').write_text(build_html(report))


def build_markdown(report: dict) -> str:
    lines = [
        f"# Eval Report - {report['bench_run_id']}",
        '',
        f"- pipeline: {report['pipeline']}",
        f"- profile: {report['profile']}",
        f"- total cases: {len(report['cases'])}",
        '',
        '| case_id | score | passed | reason |',
        '| --- | --- | --- | --- |',
    ]
    for case in report['cases']:
        lines.append(f"| {case['case_id']} | {case['judge']['score']:.2f} | {case['judge']['pass']} | {case['judge']['reason']} |")
    return '\n'.join(lines)


def build_html(report: dict) -> str:
    rows = ''.join(
        f"<tr><td>{case['case_id']}</td><td>{case['judge']['score']:.2f}</td><td>{case['judge']['pass']}</td><td>{case['judge']['reason']}</td></tr>"
        for case in report['cases']
    )
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>Eval Report {report['bench_run_id']}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; color: #1f2937; }}
    .cards {{ display: flex; gap: 16px; margin-bottom: 24px; }}
    .card {{ padding: 16px 20px; border-radius: 16px; background: #f3f4f6; min-width: 160px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 10px 8px; text-align: left; }}
  </style>
</head>
<body>
  <h1>评测报告</h1>
  <div class="cards">
    <div class="card"><strong>Pipeline</strong><div>{report['pipeline']}</div></div>
    <div class="card"><strong>Profile</strong><div>{report['profile']}</div></div>
    <div class="card"><strong>Cases</strong><div>{len(report['cases'])}</div></div>
  </div>
  <table>
    <thead><tr><th>Case</th><th>Score</th><th>Pass</th><th>Reason</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</body>
</html>'''
