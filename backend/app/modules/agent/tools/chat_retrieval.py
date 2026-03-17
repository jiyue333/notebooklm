"""聊天检索工具。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.tools import ToolRuntime
from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notebooks.models import Article, ArticleChunk

@dataclass(slots=True)
class ChatToolContext:
    db: AsyncSession
    article_id: str | None
    notebook_id: str
    user_id: str


@tool
async def search_article_chunks(
    query: str,
    runtime: ToolRuntime[ChatToolContext, dict[str, Any]],
) -> str:
    """在当前文章内检索相关片段。"""
    db = runtime.context.db
    article_id = runtime.context.article_id
    if not db or not article_id:
        return "No article selected."

    result = await db.execute(
        select(ArticleChunk)
        .where(ArticleChunk.article_id == article_id)
        .order_by(ArticleChunk.chunk_index.asc())
        .limit(30)
    )
    chunks = list(result.scalars().all())
    if not chunks:
        return "No content found in this article."

    query_words = set(query.lower().split())
    scored = []
    for chunk in chunks:
        chunk_words = set((chunk.chunk_text or "").lower().split())
        overlap = len(query_words & chunk_words)
        if overlap > 0:
            scored.append((chunk, overlap))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:5]
    if not top:
        return "No relevant passages found for this query."

    parts = []
    for i, (c, _) in enumerate(top, 1):
        section = c.section_path or c.heading_title or ""
        text = (c.chunk_text or "")[:400]
        parts.append(f"[{i}] {f'({section}) ' if section else ''}{text}")
    return "\n\n".join(parts)


@tool
async def search_notebook_articles(
    query: str,
    runtime: ToolRuntime[ChatToolContext, dict[str, Any]],
) -> str:
    """在当前 notebook 的全部文章中检索。"""
    db = runtime.context.db
    notebook_id = runtime.context.notebook_id
    user_id = runtime.context.user_id
    article_id = runtime.context.article_id
    if not db or not notebook_id or not user_id:
        return "No notebook context available."

    stmt = select(Article).where(
        Article.notebook_id == notebook_id,
        Article.user_id == user_id,
    )
    if article_id:
        stmt = stmt.where(Article.id != article_id)
    result = await db.execute(stmt.limit(30))
    articles = list(result.scalars().all())

    if not articles:
        return "No other articles found in this notebook."

    query_words = set(query.lower().split())
    scored = []
    for art in articles:
        title_words = set((art.title or "").lower().split())
        preview_words = set((art.preview_markdown or "")[:500].lower().split())
        overlap = len(query_words & (title_words | preview_words))
        if overlap > 0:
            scored.append((art, overlap))

    scored.sort(key=lambda x: x[1], reverse=True)
    top = scored[:5]
    if not top:
        return "No relevant articles found for this query."

    parts = []
    for i, (a, _) in enumerate(top, 1):
        preview = (a.preview_markdown or "")[:200]
        parts.append(f"[{i}] **{a.title}**\n{preview}")
    return "\n\n".join(parts)
