from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def add_common_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", required=True, help="Path to output JSON or JSONL file")


def add_report_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--baseline",
        help="Optional baseline JSON report to compare against",
    )
    parser.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="Exit with non-zero status when baseline comparison contains regressions",
    )
    parser.add_argument(
        "--markdown-output",
        help="Optional Markdown report path",
    )
    parser.add_argument(
        "--prometheus-output",
        help="Optional Prometheus textfile output path",
    )


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
