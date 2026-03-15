"""File parser adapter – MarkItDown for PDF, Word, PowerPoint, etc."""

from __future__ import annotations

import tempfile
from pathlib import Path

import structlog

from app.modules.ingest.pipeline.types import ParseCandidate

logger = structlog.get_logger(__name__)

async def parse_file(
    raw_bytes: bytes,
    file_name: str | None = None,
    file_ext: str | None = None,
) -> ParseCandidate | None:
    """Convert a binary file to markdown using MarkItDown."""

    try:
        from markitdown import MarkItDown
    except ImportError:
        logger.warning("ingest.parser.markitdown_unavailable")
        return None

    ext = file_ext or (Path(file_name).suffix if file_name else "")
    if not ext:
        return None

    suffix = ext if ext.startswith(".") else f".{ext}"
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = tmp.name

        converter = MarkItDown()
        result = converter.convert(tmp_path)
        markdown = (result.text_content or "").strip()
        if not markdown:
            return None

        title = getattr(result, "title", None)

        return ParseCandidate(
            parser_name="markitdown",
            markdown=markdown,
            title=title,
            word_count=len(markdown.split()),
        )
    except Exception as exc:
        logger.warning(
            "ingest.parser.markitdown_error",
            file_name=file_name,
            error=str(exc),
        )
        return None
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
