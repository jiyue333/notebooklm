from __future__ import annotations

import argparse
from typing import Any

from backend.evals.common.cli import add_common_output_args
from backend.evals.common.jsonl import read_jsonl, write_jsonl


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "article_id": case.get("article_id"),
        "reference_summary": str(case.get("reference_summary", "")).strip(),
        "required_phrases": list(dict.fromkeys(case.get("required_phrases", []))),
        "source_chars": int(case.get("source_chars", 0) or 0),
        "readability_expectation": case.get("readability_expectation", "normal"),
        "difficulty": case.get("difficulty", "normal"),
        "notes": str(case.get("notes", "")).strip(),
        "tags": list(dict.fromkeys(case.get("tags", []))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize summary dataset JSONL")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    add_common_output_args(parser)
    args = parser.parse_args()
    rows = [_normalize_case(row) for row in read_jsonl(args.input)]
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
