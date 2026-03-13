from __future__ import annotations

import argparse
from typing import Any

from backend.evals.common.cli import add_common_output_args
from backend.evals.common.jsonl import read_jsonl, write_jsonl


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "query": str(case["query"]).strip(),
        "difficulty": case.get("difficulty", "normal"),
        "query_intent": case.get("query_intent", "unknown"),
        "domain": case.get("domain", "general"),
        "freshness_requirement": case.get("freshness_requirement", "none"),
        "authority_requirement": case.get("authority_requirement", "none"),
        "expected_docs": list(dict.fromkeys(case.get("expected_docs", []))),
        "acceptable_docs": list(dict.fromkeys(case.get("acceptable_docs", []))),
        "bad_docs": list(dict.fromkeys(case.get("bad_docs", []))),
        "corpus_version": case.get("corpus_version", "unknown"),
        "notes": str(case.get("notes", "")).strip(),
        "tags": list(dict.fromkeys(case.get("tags", []))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize search dataset JSONL")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    add_common_output_args(parser)
    args = parser.parse_args()
    rows = [_normalize_case(row) for row in read_jsonl(args.input)]
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
