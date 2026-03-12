from __future__ import annotations

from app.infra.providers.exa.contents_client import ExaContentsClient, ExaContentsRequest
from app.modules.search.markdown_utils import build_image_markdown, contains_image_markup


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
    markdown = str(item.get("text") or item.get("content") or "").strip()
    lead_image = str(item.get("image") or "").strip()
    title = str(item.get("title") or url).strip()
    if lead_image and not contains_image_markup(markdown):
        markdown = build_image_markdown(
            title=title,
            image_url=lead_image,
            body=markdown,
        ).strip()
    return (markdown or None), "exa_contents"
