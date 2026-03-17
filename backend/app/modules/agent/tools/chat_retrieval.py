"""Retrieval tools for the chat agent.

These are LangChain tools that the LangGraph ReAct agent can call.
The agent decides when and how many times to call them.
"""

from __future__ import annotations

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notebooks.models import Article, ArticleChunk

_DB_SESSION: AsyncSession | None = None
_CONTEXT: dict = {}


def set_tool_context(db: AsyncSession, **kwargs) -> None:
    """Set the DB session and context for tool execution.

    Called before the agent runs so tools can access the database.
    """
    global _DB_SESSION, _CONTEXT
    _DB_SESSION = db
    _CONTEXT = kwargs


@tool
async def search_article_chunks(query: str) -> str:
    """Search within the current article for relevant passages.

    Use this when the user asks about content in the article they're reading.
    Returns matching text passages from the article.
    """
    db = _DB_SESSION
    article_id = _CONTEXT.get("article_id")
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
async def search_notebook_articles(query: str) -> str:
    """Search across all articles in the user's notebook.

    Use this when the user asks about topics across their research,
    wants to find similar content, or asks a research synthesis question.
    Returns matching article titles and previews.
    """
    db = _DB_SESSION
    notebook_id = _CONTEXT.get("notebook_id")
    user_id = _CONTEXT.get("user_id")
    article_id = _CONTEXT.get("article_id")
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
