from __future__ import annotations

import argparse

from backend.evals.common.http_client import NotebooklmClient
from backend.evals.common.jsonl import read_jsonl
from backend.evals.online_seed.common import ensure_demo_notebooks, ensure_ready_article


def main() -> None:
    parser = argparse.ArgumentParser(description="Create summary runs from JSONL cases")
    parser.add_argument("--input", help="JSONL with notebook_id and article_id")
    parser.add_argument("--count", type=int, default=2, help="Notebook count for one-click summary mode")
    args = parser.parse_args()
    client = NotebooklmClient.from_env()
    if args.input:
        rows = read_jsonl(args.input)
    else:
        notebooks = ensure_demo_notebooks(client, count=args.count)
        rows = []
        for notebook in notebooks:
            article = ensure_ready_article(client, notebook["id"])
            rows.append({"notebook_id": notebook["id"], "article_id": article["id"]})

    for row in rows:
        payload = client.post(
            f"/notebooks/{row['notebook_id']}/articles/{row['article_id']}/summary"
        )
        print(payload.get("item", payload))


if __name__ == "__main__":
    main()
