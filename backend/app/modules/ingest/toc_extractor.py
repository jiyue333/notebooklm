from __future__ import annotations

from app.modules.search.markdown_utils import extract_toc


def extract_toc_items(markdown: str) -> list[dict]:
    return extract_toc(markdown)
