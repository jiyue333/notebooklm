from __future__ import annotations

import argparse

from backend.evals.common.http_client import NotebooklmClient
from backend.evals.common.jsonl import read_jsonl
from backend.evals.online_seed.common import ensure_demo_notebooks, ensure_ready_article

DEFAULT_CHAT_MESSAGE = "请总结当前文章，并说明我们应该重点看哪些观测指标。"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create chat threads from JSONL prompts")
    parser.add_argument("--input", help="JSONL with notebook_id, article_id, conversation_id, message")
    parser.add_argument("--count", type=int, default=2, help="Notebook count for one-click chat mode")
    parser.add_argument("--message", default=DEFAULT_CHAT_MESSAGE, help="Default message in one-click mode")
    args = parser.parse_args()
    client = NotebooklmClient.from_env()
    if args.input:
        rows = read_jsonl(args.input)
    else:
        notebooks = ensure_demo_notebooks(client, count=args.count)
        rows = []
        for notebook in notebooks:
            article = ensure_ready_article(client, notebook["id"])
            rows.append(
                {
                    "notebook_id": notebook["id"],
                    "article_id": article["id"],
                    "conversation_id": None,
                    "message": args.message,
                }
            )

    for row in rows:
        payload = client.post_stream(
            f"/notebooks/{row['notebook_id']}/chat/stream",
            {
                "articleId": row.get("article_id"),
                "conversationId": row.get("conversation_id"),
                "message": row["message"],
            },
        )
        print(payload.get("item", payload))


if __name__ == "__main__":
    main()
