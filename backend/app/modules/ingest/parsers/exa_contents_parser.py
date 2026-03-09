from __future__ import annotations

from app.infra.providers.exa.contents_client import ExaContentsClient, ExaContentsRequest


async def fetch_markdown_with_exa(*, url: str, api_key: str) -> tuple[str | None, str]:
    client = ExaContentsClient()
    try:
        payload = await client.fetch(
            ExaContentsRequest(
                urls=[url],
                include_text=True,
                include_summary=False,
                include_highlights=False,
                livecrawl="preferred",
            ),
            api_key=api_key,
        )
    finally:
        await client.close()

    results = payload.get("results") or payload.get("data") or []
    if not results:
        return None, "exa_contents"

    item = results[0]
    markdown = item.get("text") or item.get("content")
    return (str(markdown).strip() if markdown else None), "exa_contents"
