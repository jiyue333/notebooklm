"""Stage G – TOC Generation & Anchor Binding.

Extracts or synthesises a table-of-contents from the fused markdown.
Each TOCNode carries an anchor that maps to a line range in the
document so the reader view can jump to the right section.
"""

from __future__ import annotations

import re

from app.modules.ingest.pipeline.types import FusedDocument, TOCNode


def build_toc(doc: FusedDocument) -> list[TOCNode]:
    """Return a list of TOC nodes for the fused document."""

    nodes = _extract_from_headings(doc.clean_markdown)
    if nodes:
        return nodes

    # No headings found – generate a synthetic TOC from paragraphs.
    return _synthesize_toc(doc.clean_markdown)


# ── heading-based extraction ───────────────────────────────────────────────

def _extract_from_headings(md: str) -> list[TOCNode]:
    nodes: list[TOCNode] = []
    in_code = False
    skipped_first_h1 = False

    for line_no, line in enumerate(md.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not line.startswith("#"):
            continue

        parts = stripped.split(" ", 1)
        if len(parts) != 2:
            continue
        level = len(parts[0])
        if level < 1 or level > 4:
            continue
        title = parts[1].strip()
        if not title:
            continue

        if level == 1 and not skipped_first_h1:
            skipped_first_h1 = True
            continue

        node_id = _slugify(title)
        nodes.append(TOCNode(
            id=node_id,
            title=title,
            level=level,
            anchor=f"L{line_no}",
            is_synthetic=False,
        ))

    return nodes


# ── synthetic TOC (when no headings exist) ─────────────────────────────────

_MIN_SECTION_LINES = 8


def _synthesize_toc(md: str) -> list[TOCNode]:
    """Split the document into rough sections and name them."""

    lines = md.splitlines()
    if len(lines) < _MIN_SECTION_LINES:
        return []

    boundaries = _detect_boundaries(lines)
    if not boundaries:
        return []

    nodes: list[TOCNode] = []
    for idx, start_line in enumerate(boundaries):
        end_line = boundaries[idx + 1] if idx + 1 < len(boundaries) else len(lines)
        section_text = "\n".join(lines[start_line:end_line]).strip()
        if not section_text:
            continue
        title = _name_section(section_text, idx + 1)
        node_id = _slugify(title)
        nodes.append(TOCNode(
            id=node_id,
            title=title,
            level=2,
            anchor=f"L{start_line + 1}",
            is_synthetic=True,
        ))

    return nodes


def _detect_boundaries(lines: list[str]) -> list[int]:
    """Find section boundaries by blank-line clusters and length patterns."""

    boundaries: list[int] = [0]
    consecutive_blanks = 0

    for i, line in enumerate(lines):
        if not line.strip():
            consecutive_blanks += 1
        else:
            if consecutive_blanks >= 2 and i - boundaries[-1] >= _MIN_SECTION_LINES:
                boundaries.append(i)
            consecutive_blanks = 0

    return boundaries


def _name_section(text: str, index: int) -> str:
    """Extract a short title from the first meaningful line of a section."""

    for line in text.splitlines():
        stripped = line.strip()
        if stripped and len(stripped) >= 5:
            candidate = stripped[:80].rstrip(".")
            if len(candidate) > 60:
                candidate = candidate[:57] + "..."
            return candidate
    return f"Section {index}"


def _slugify(title: str) -> str:
    result: list[str] = []
    for ch in title.lower():
        if ch.isalnum() or "\u4e00" <= ch <= "\u9fff":
            result.append(ch)
        else:
            result.append("-")
    slug = "".join(result).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug
