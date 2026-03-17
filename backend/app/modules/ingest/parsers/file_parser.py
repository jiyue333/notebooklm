"""File parser adapter – delegates to ``infra.providers.mineru``."""

from __future__ import annotations

from pathlib import Path

import structlog

from app.infra.providers.mineru.client import MinerUClient
from app.modules.ingest.pipeline.types import ParseCandidate

logger = structlog.get_logger(__name__)


async def parse_file(
    raw_bytes: bytes,
    file_name: str | None = None,
    file_ext: str | None = None,
) -> ParseCandidate | None:
    """Convert a binary file to markdown using MinerU."""

    ext = file_ext or (Path(file_name).suffix if file_name else "")
    if not ext:
        return None

    client = MinerUClient()
    markdown = await client.parse(raw_bytes, file_ext=ext)
    if not markdown:
        logger.warning("ingest.parser.mineru_failed", file_name=file_name)
        return None

    title = _extract_title(markdown)
    return ParseCandidate(
        parser_name="mineru",
        markdown=markdown,
        title=title or (Path(file_name).stem if file_name else None),
        word_count=len(markdown.split()),
    )


def _extract_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return None
