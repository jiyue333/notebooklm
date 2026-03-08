from __future__ import annotations

from pathlib import Path


def convert_file_to_markdown(path: Path) -> tuple[str, str] | None:
    try:
        from markitdown import MarkItDown
    except ImportError:
        return None

    converter = MarkItDown()
    result = converter.convert(str(path))
    markdown = getattr(result, "markdown", None) or getattr(result, "text_content", None)
    if not markdown:
        return None
    return str(markdown).strip(), "markitdown"
