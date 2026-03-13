from __future__ import annotations

from backend.evals.common.http_client import NotebooklmClient

DEFAULT_NOTEBOOK_TITLE_PREFIX = "Observability Demo"
DEFAULT_TEXT_SOURCE = """# Observability Seed Article

## Search

- latency
- quality
- sampled review

## Ingest

- parse ready
- structure quality
- chunking

## AI

- first token
- groundedness
- completeness
"""


def list_notebooks(client: NotebooklmClient) -> list[dict]:
    payload = client.get("/notebooks")
    return list(payload.get("items", []))


def ensure_demo_notebooks(
    client: NotebooklmClient,
    *,
    count: int = 3,
    title_prefix: str = DEFAULT_NOTEBOOK_TITLE_PREFIX,
) -> list[dict]:
    notebooks = list_notebooks(client)
    while len(notebooks) < count:
        created = client.post(
            "/notebooks",
            {
                "title": f"{title_prefix} {len(notebooks) + 1}",
                "emoji": "📘",
                "color": "#3b82f6",
            },
        )
        item = created.get("item", {})
        notebooks.append(item)
    return notebooks[:count]


def get_notebook_detail(client: NotebooklmClient, notebook_id: str) -> dict:
    payload = client.get(f"/notebooks/{notebook_id}")
    return payload.get("item", {})


def ensure_ready_article(client: NotebooklmClient, notebook_id: str) -> dict:
    detail = get_notebook_detail(client, notebook_id)
    for article in detail.get("articles", []):
        if article.get("contentReady"):
            return article

    created = client.post(
        f"/notebooks/{notebook_id}/sources",
        {
            "sourceType": "text",
            "title": "Observability Seed Article",
            "content": DEFAULT_TEXT_SOURCE,
        },
    )
    detail = created.get("item", {}) or get_notebook_detail(client, notebook_id)
    for article in detail.get("articles", []):
        if article.get("contentReady"):
            return article
    raise RuntimeError("failed to create a ready article for online seed")
