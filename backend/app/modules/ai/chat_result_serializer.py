from __future__ import annotations

from app.modules.retrieval.article_retriever import RetrievedArticleMatch
from app.modules.retrieval.chunk_retriever import RetrievedChunkMatch


def serialize_related_match(match: RetrievedArticleMatch) -> dict:
    article = match.article
    notebook = getattr(article, "notebook", None)
    return {
        "articleId": article.id,
        "title": article.title,
        "notebookId": article.notebook_id,
        "notebookTitle": getattr(notebook, "title", None),
        "author": article.author,
        "date": (article.published_at or article.created_at).isoformat(),
        "snippet": match.snippet,
        "score": match.score,
        "matchedBy": match.matched_by,
    }


def serialize_chunk_match(match: RetrievedChunkMatch, *, notebook_title: str) -> dict:
    article = match.article
    chunk = match.chunk
    return {
        "articleId": article.id,
        "chunkId": chunk.id,
        "title": article.title,
        "notebookId": article.notebook_id,
        "notebookTitle": notebook_title,
        "headingTitle": chunk.heading_title,
        "sectionPath": chunk.section_path,
        "snippet": match.snippet,
        "score": match.score,
        "matchedBy": match.matched_by,
    }


def build_retrieval_snapshot(
    *,
    route: str,
    route_reason: str,
    route_confidence: float,
    query: str,
    retrieval_details: dict,
) -> dict:
    return {
        "route": route,
        "routeReason": route_reason,
        "routeConfidence": route_confidence,
        "query": query,
        **retrieval_details,
    }


def build_chat_response(
    *,
    conversation_id: str,
    message_id: str,
    route: str,
    reply: str,
    citations: list[dict],
    retrieval_snapshot: dict,
) -> dict:
    return {
        "conversationId": conversation_id,
        "messageId": message_id,
        "route": route,
        "reply": reply,
        "citations": citations,
        "retrievalSnapshot": retrieval_snapshot,
    }
