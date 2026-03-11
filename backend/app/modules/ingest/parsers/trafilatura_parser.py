from __future__ import annotations


def fetch_markdown_with_trafilatura(*, url: str) -> tuple[str | None, str]:
    try:
        import trafilatura
    except ModuleNotFoundError:
        return None, "trafilatura"

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None, "trafilatura"
    markdown = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_links=True,
        include_tables=True,
    )
    return (markdown.strip() if markdown else None), "trafilatura"
