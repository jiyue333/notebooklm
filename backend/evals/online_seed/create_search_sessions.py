from __future__ import annotations

import argparse

from backend.evals.common.http_client import NotebooklmClient
from backend.evals.common.jsonl import read_jsonl
from backend.evals.online_seed.common import ensure_demo_notebooks

DEFAULT_SEARCH_QUERIES = [
    "latest ai observability best practices",
    "redis bigkey hotkey analysis guide",
    "kafka consumer lag and summary latency correlation",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create search sessions from JSONL cases")
    parser.add_argument("--input", help="JSONL with notebook_id, query, mode, max_results, freshness_hours")
    parser.add_argument("--count", type=int, default=3, help="Notebook count for default seed mode")
    parser.add_argument("--mode", default="fast", help="Default search mode in one-click mode")
    parser.add_argument("--max-results", type=int, default=10, help="Default maxResults in one-click mode")
    parser.add_argument("--freshness-hours", type=int, default=24, help="Default freshnessHours in one-click mode")
    args = parser.parse_args()
    client = NotebooklmClient.from_env()
    if args.input:
        rows = read_jsonl(args.input)
    else:
        notebooks = ensure_demo_notebooks(client, count=args.count)
        rows = [
            {
                "notebook_id": notebook["id"],
                "query": DEFAULT_SEARCH_QUERIES[index % len(DEFAULT_SEARCH_QUERIES)],
                "mode": args.mode,
                "max_results": args.max_results,
                "freshness_hours": args.freshness_hours,
            }
            for index, notebook in enumerate(notebooks)
        ]

    for row in rows:
        payload = client.post(
            f"/notebooks/{row['notebook_id']}/sources/search",
            {
                "query": row["query"],
                "mode": row.get("mode", args.mode),
                "maxResults": row.get("max_results", args.max_results),
                "freshnessHours": row.get("freshness_hours", args.freshness_hours),
            },
        )
        print(payload.get("item", payload))


if __name__ == "__main__":
    main()
