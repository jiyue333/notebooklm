from __future__ import annotations

import argparse
from typing import Any

from backend.evals.common.cli import add_common_output_args
from backend.evals.common.jsonl import read_jsonl, write_jsonl


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "doc_type": case.get("doc_type", "unknown"),
        "parser_family": case.get("parser_family", "unknown"),
        "expect_ocr": bool(case.get("expect_ocr", False)),
        "source_path": case.get("source_path", ""),
        "reference_markdown": str(case.get("reference_markdown", "")).strip(),
        "expected_fields": case.get("expected_fields", {}),
        "required_phrases": list(dict.fromkeys(case.get("required_phrases", []))),
        "structure_expectations": case.get(
            "structure_expectations",
            {"title_hierarchy": False, "list": False, "table": False, "image": False, "link": False},
        ),
        "notes": str(case.get("notes", "")).strip(),
        "tags": list(dict.fromkeys(case.get("tags", []))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize ingest dataset JSONL")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    add_common_output_args(parser)
    args = parser.parse_args()
    rows = [_normalize_case(row) for row in read_jsonl(args.input)]
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
