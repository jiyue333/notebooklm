from __future__ import annotations

import argparse
from typing import Any

from backend.evals.common.cli import add_common_output_args
from backend.evals.common.jsonl import read_jsonl, write_jsonl


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": str(case["case_id"]),
        "question": str(case["question"]).strip(),
        "reference_answer": str(case.get("reference_answer", "")).strip(),
        "query_intent": case.get("query_intent", "question_answering"),
        "domain": case.get("domain", "general"),
        "expected_context_ids": list(dict.fromkeys(case.get("expected_context_ids", []))),
        "acceptable_context_ids": list(dict.fromkeys(case.get("acceptable_context_ids", []))),
        "expected_citation_ids": list(dict.fromkeys(case.get("expected_citation_ids", []))),
        "required_phrases": list(dict.fromkeys(case.get("required_phrases", []))),
        "behavior_expectations": case.get(
            "behavior_expectations",
            {
                "safe_refusal_expected": False,
                "tool_call_expected": False,
                "multi_turn_consistency": False,
            },
        ),
        "notes": str(case.get("notes", "")).strip(),
        "tags": list(dict.fromkeys(case.get("tags", []))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize RAG dataset JSONL")
    parser.add_argument("--input", required=True, help="Input JSONL path")
    add_common_output_args(parser)
    args = parser.parse_args()
    rows = [_normalize_case(row) for row in read_jsonl(args.input)]
    write_jsonl(args.output, rows)


if __name__ == "__main__":
    main()
