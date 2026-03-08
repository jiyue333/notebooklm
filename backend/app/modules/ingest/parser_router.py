from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.modules.ingest.parsers.markitdown_parser import convert_file_to_markdown
from app.modules.search.markdown_utils import decode_text_bytes, normalize_text_to_markdown


@dataclass(slots=True)
class ParsedContent:
    markdown: str | None
    parser_name: str | None


def parse_file_content(
    *,
    file_name: str | None,
    file_path: Path,
    file_bytes: bytes,
) -> ParsedContent:
    suffix = Path(file_name or "").suffix.lower()
    title = (file_name or "未命名文件").strip()

    if suffix == ".md":
        return ParsedContent(markdown=decode_text_bytes(file_bytes), parser_name="raw_markdown")
    if suffix == ".txt":
        return ParsedContent(
            markdown=normalize_text_to_markdown(title=title, content=decode_text_bytes(file_bytes)),
            parser_name="plain_text",
        )

    markdown_result = convert_file_to_markdown(file_path)
    if markdown_result is None:
        return ParsedContent(markdown=None, parser_name=None)
    markdown, parser_name = markdown_result
    return ParsedContent(markdown=markdown, parser_name=parser_name)
