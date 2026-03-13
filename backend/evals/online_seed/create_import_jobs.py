from __future__ import annotations

import argparse

from backend.evals.common.http_client import NotebooklmClient
from backend.evals.common.jsonl import read_jsonl
from backend.evals.online_seed.common import ensure_demo_notebooks

DEFAULT_IMPORT_QUERY = "observability dashboards for search ingest ai"


def main() -> None:
    parser = argparse.ArgumentParser(description="Import search results into notebooks")
    parser.add_argument("--input", help="JSONL with notebook_id, search_session_id, search_result_ids or top_k")
    parser.add_argument("--count", type=int, default=2, help="Notebook count for one-click import mode")
    parser.add_argument("--top-k", type=int, default=2, help="How many search results to import in one-click mode")
    parser.add_argument("--mode", default="fast", help="Search mode used to create candidate results in one-click mode")
    args = parser.parse_args()
    client = NotebooklmClient.from_env()
    if args.input:
        rows = read_jsonl(args.input)
    else:
        notebooks = ensure_demo_notebooks(client, count=args.count)
        rows = []
        for notebook in notebooks:
            search_payload = client.post(
                f"/notebooks/{notebook['id']}/sources/search",
                {
                    "query": DEFAULT_IMPORT_QUERY,
                    "mode": args.mode,
                    "maxResults": max(args.top_k, 3),
                    "freshnessHours": 24,
                },
            )
            rows.append(
                {
                    "notebook_id": notebook["id"],
                    "search_session_id": search_payload["item"]["searchSessionId"],
                    "search_result_ids": [item["id"] for item in search_payload.get("items", [])[: args.top_k]],
                    "top_k": args.top_k,
                }
            )

    for row in rows:
        result_ids = list(row.get("search_result_ids", []))
        if not result_ids and row.get("top_k"):
            session = client.get(f"/notebooks/{row['notebook_id']}/search-sessions/{row['search_session_id']}")
            items = session.get("items", [])
            result_ids = [item["id"] for item in items[: int(row["top_k"])]]
        if not result_ids:
            continue
        payload = client.post(
            f"/notebooks/{row['notebook_id']}/sources/import",
            {
                "searchSessionId": row["search_session_id"],
                "searchResultIds": result_ids,
            },
        )
        print(payload.get("item", payload))


if __name__ == "__main__":
    main()
