"""Text / Markdown direct parser – pass-through with minimal normalization."""

from __future__ import annotations

from app.modules.ingest.pipeline.types import ParseCandidate


def parse_text(
    raw_text: str,
    title: str | None = None,
) -> ParseCandidate | None:
    """Normalize raw text/markdown into a ParseCandidate."""

    content = raw_text.strip()
    if not content:
        return None

    if title and not content.startswith("#"):
        content = f"# {title}\n\n{content}"

    return ParseCandidate(
        parser_name="text_direct",
        markdown=content,
        title=title,
        word_count=len(content.split()),
    )


def decode_text_bytes(data: bytes) -> str:
    """Try common encodings to decode raw bytes to text."""
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
