"""Stage H – BlockGraph Construction.

Parses the fused markdown into a structured graph of typed blocks
with parent/next edges based on heading hierarchy.
"""

from __future__ import annotations

import re
import uuid

from app.modules.ingest.pipeline.types import (
    Block,
    BlockEdge,
    BlockGraph,
    BlockType,
    FusedDocument,
    TOCNode,
)


def build_block_graph(
    doc: FusedDocument,
    toc: list[TOCNode],
) -> BlockGraph:
    """Parse *doc* into blocks and wire parent/next edges."""

    blocks = _parse_blocks(doc.clean_markdown)
    edges = _build_edges(blocks)
    _assign_sections(blocks, toc)
    return BlockGraph(blocks=blocks, edges=edges)


# ── block parsing ──────────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)")
_LIST_RE = re.compile(r"^[\s]*[-*+]\s|^[\s]*\d+\.\s")
_TABLE_RE = re.compile(r"^\|")
_QUOTE_RE = re.compile(r"^>\s?")


def _parse_blocks(md: str) -> list[Block]:
    lines = md.splitlines()
    blocks: list[Block] = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # skip blank lines
        if not stripped:
            i += 1
            continue

        # code block
        if stripped.startswith("```"):
            start = i
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            i += 1  # skip closing ```
            text = "\n".join(lines[start:i])
            blocks.append(_block(BlockType.CODE, text, start, i - 1))
            continue

        # heading
        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            blocks.append(_block(BlockType.HEADING, stripped, i, i, level=level))
            i += 1
            continue

        # table
        if _TABLE_RE.match(stripped):
            start = i
            while i < len(lines) and _TABLE_RE.match(lines[i].strip()):
                i += 1
            text = "\n".join(lines[start:i])
            blocks.append(_block(BlockType.TABLE, text, start, i - 1))
            continue

        # blockquote
        if _QUOTE_RE.match(line):
            start = i
            while i < len(lines) and _QUOTE_RE.match(lines[i]):
                i += 1
            text = "\n".join(lines[start:i])
            blocks.append(_block(BlockType.QUOTE, text, start, i - 1))
            continue

        # list
        if _LIST_RE.match(line):
            start = i
            while i < len(lines) and (
                _LIST_RE.match(lines[i]) or (lines[i].startswith("  ") and lines[i].strip())
            ):
                i += 1
            text = "\n".join(lines[start:i])
            blocks.append(_block(BlockType.LIST, text, start, i - 1))
            continue

        # paragraph (default)
        start = i
        while i < len(lines) and lines[i].strip() and not _is_structural(lines[i]):
            i += 1
        text = "\n".join(lines[start:i])
        blocks.append(_block(BlockType.PARAGRAPH, text, start, i - 1))

    return blocks


def _is_structural(line: str) -> bool:
    s = line.strip()
    return bool(
        s.startswith("#")
        or s.startswith("```")
        or _TABLE_RE.match(s)
        or _QUOTE_RE.match(line)
        or _LIST_RE.match(line)
    )


def _block(
    bt: BlockType,
    text: str,
    line_start: int,
    line_end: int,
    level: int = 0,
) -> Block:
    return Block(
        block_id=uuid.uuid4().hex[:12],
        block_type=bt,
        text=text,
        level=level,
        line_start=line_start + 1,  # 1-indexed
        line_end=line_end + 1,
    )


# ── edge building ──────────────────────────────────────────────────────────

def _build_edges(blocks: list[Block]) -> list[BlockEdge]:
    edges: list[BlockEdge] = []
    heading_stack: list[Block] = []

    for i, b in enumerate(blocks):
        # next edge
        if i > 0:
            edges.append(BlockEdge(
                source_id=blocks[i - 1].block_id,
                target_id=b.block_id,
                relation="next",
            ))

        # parent edge (heading hierarchy)
        if b.block_type == BlockType.HEADING:
            while heading_stack and heading_stack[-1].level >= b.level:
                heading_stack.pop()
            if heading_stack:
                edges.append(BlockEdge(
                    source_id=heading_stack[-1].block_id,
                    target_id=b.block_id,
                    relation="parent_of",
                ))
            heading_stack.append(b)
        elif heading_stack:
            edges.append(BlockEdge(
                source_id=heading_stack[-1].block_id,
                target_id=b.block_id,
                relation="parent_of",
            ))

    return edges


# ── section assignment ─────────────────────────────────────────────────────

def _assign_sections(blocks: list[Block], toc: list[TOCNode]) -> None:
    """Assign section_id to each block based on the nearest preceding heading."""

    if not toc:
        return

    current_section: str | None = None
    toc_ids = {n.id for n in toc}
    heading_map: dict[str, str] = {}

    for b in blocks:
        if b.block_type == BlockType.HEADING:
            slug = b.text.strip().lstrip("#").strip()
            slug_id = _slugify_quick(slug)
            if slug_id in toc_ids:
                current_section = slug_id
                heading_map[b.block_id] = slug_id
        b.section_id = current_section


def _slugify_quick(title: str) -> str:
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
