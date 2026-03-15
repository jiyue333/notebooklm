"""HTML parser adapters – Trafilatura and Exa Contents API."""

from __future__ import annotations

import structlog

from app.modules.ingest.pipeline.types import ParseCandidate

logger = structlog.get_logger(__name__)


async def parse_html_trafilatura(
    url: str,
    raw_html: bytes | None = None,
) -> ParseCandidate | None:
    """Extract main content from a URL using Trafilatura."""

    try:
        import trafilatura  # optional dependency
    except ImportError:
        logger.warning("ingest.parser.trafilatura_unavailable")
        return None

    try:
        if raw_html:
            html_str = raw_html.decode("utf-8", errors="replace")
        else:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                return None
            html_str = downloaded

        result = trafilatura.extract(
            html_str,
            output_format="txt",
            include_links=True,
            include_tables=True,
            include_images=True,
            favor_recall=True,
        )
        if not result or not result.strip():
            return None

        metadata = trafilatura.extract_metadata(html_str)
        title = getattr(metadata, "title", None) if metadata else None
        author = getattr(metadata, "author", None) if metadata else None
        date = getattr(metadata, "date", None) if metadata else None

        published_at = None
        if date:
            from datetime import datetime
            try:
                published_at = datetime.fromisoformat(str(date))
            except (ValueError, TypeError):
                pass

        markdown = result.strip()
        if title:
            markdown = f"# {title}\n\n{markdown}"

        return ParseCandidate(
            parser_name="trafilatura",
            markdown=markdown,
            title=title,
            author=author,
            published_at=published_at,
            word_count=len(markdown.split()),
        )
    except Exception as exc:
        logger.warning("ingest.parser.trafilatura_error", url=url, error=str(exc))
        return None


async def parse_html_exa(
    url: str,
    *,
    exa_api_key: str,
) -> ParseCandidate | None:
    """Fetch structured content via Exa Contents API."""

    try:
        from app.infra.providers.exa.contents_client import (
            ExaContentsClient,
            ExaContentsRequest,
        )
    except ImportError:
        logger.warning("ingest.parser.exa_unavailable")
        return None

    client = ExaContentsClient()
    try:
        request = ExaContentsRequest(urls=[url])
        payload = await client.fetch(request, api_key=exa_api_key)
    except Exception as exc:
        logger.warning("ingest.parser.exa_error", url=url, error=str(exc))
        return None
    finally:
        await client.close()

    if not payload:
        return None

    results = payload.get("results") or []
    first = results[0] if results else {}
    text = first.get("text") or ""
    title = first.get("title")
    author = first.get("author")

    if not text.strip():
        return None

    markdown = text.strip()
    if title:
        markdown = f"# {title}\n\n{markdown}"

    return ParseCandidate(
        parser_name="exa",
        markdown=markdown,
        title=title,
        author=author,
        word_count=len(markdown.split()),
        metadata={"exa_payload_keys": list(payload.keys())},
    )
