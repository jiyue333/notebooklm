from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(slots=True)
class ChunkDraft:
    chunk_index: int
    section_path: str | None
    heading_title: str | None
    token_count: int
    chunk_text: str


def chunk_markdown(markdown: str, *, toc: list[dict] | None = None) -> list[ChunkDraft]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    settings = get_settings()
    if not markdown.strip():
        return []

    heading_title = None
    section_path = None
    if toc:
        first_heading = toc[0]
        heading_title = str(first_heading.get("title", "")).strip() or None
        section_path = heading_title

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base",
        chunk_size=settings.chunk_target_tokens,
        chunk_overlap=settings.chunk_overlap_tokens,
        separators=["\n\n", "\n", " ", ""],
    )
    split_texts = splitter.split_text(markdown)

    chunks: list[ChunkDraft] = []
    for chunk_index, chunk_text in enumerate(split_texts):
        words = chunk_text.split()
        chunks.append(
            ChunkDraft(
                chunk_index=chunk_index,
                section_path=section_path,
                heading_title=heading_title,
                token_count=len(words),
                chunk_text=chunk_text,
            )
        )

    return chunks
