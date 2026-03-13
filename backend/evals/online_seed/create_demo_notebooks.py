from __future__ import annotations

import argparse

from backend.evals.common.http_client import NotebooklmClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Create demo notebooks via NotebookLM API")
    parser.add_argument("--count", type=int, default=3, help="Number of notebooks to create")
    parser.add_argument("--title-prefix", default="Observability Demo", help="Notebook title prefix")
    args = parser.parse_args()
    client = NotebooklmClient.from_env()
    for index in range(1, args.count + 1):
        payload = client.post(
            "/notebooks",
            {
                "title": f"{args.title_prefix} {index}",
                "emoji": "📘",
                "color": "#3b82f6",
            },
        )
        print(payload.get("item", payload))


if __name__ == "__main__":
    main()
