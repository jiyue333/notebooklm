"""HTML parser adapter – delegates to ``infra.providers.dripper``.

Fallback chain:  LLM → Dripper API → Dripper local → trafilatura.
The first three are handled by ``DripperClient``; trafilatura lives here
as the pure-algorithm last resort.
"""

from __future__ import annotations

import structlog

from app.infra.providers.dripper.client import DripperClient
from app.modules.ingest.pipeline.types import ParseCandidate

logger = structlog.get_logger(__name__)


async def parse_html(
    url: str,
    raw_html: bytes | None = None,
) -> ParseCandidate | None:
    """Extract main content from HTML."""

    html_str = raw_html.decode("utf-8", errors="replace") if raw_html else None

    client = DripperClient()
    result = await client.extract(url, html=html_str)
    if result:
        return ParseCandidate(
            parser_name=f"dripper:{result.source}",
            markdown=result.markdown,
            title=result.title,
            word_count=len(result.markdown.split()),
            metadata={"source": result.source},
        )

    return await _parse_with_trafilatura(url, html_str)


async def _parse_with_trafilatura(
    url: str,
    html_str: str | None,
) -> ParseCandidate | None:
    try:
        import trafilatura  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("ingest.parser.trafilatura_unavailable")
        return None

    try:
        if not html_str:
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
