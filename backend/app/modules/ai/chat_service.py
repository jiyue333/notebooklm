from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.notebooks import repo as notebooks_repo
from app.modules.retrieval.article_retriever import RetrievedArticleMatch, retrieve_related_articles
from app.modules.retrieval.router import route_chat_message
from app.modules.search import repo_article


async def reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
) -> dict:
    notebook = await notebooks_repo.get_notebook(session, user_id=user.id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    route = route_chat_message(message, article_id)
    next_conversation_id = conversation_id or f"conv-{uuid4()}"
    message_id = f"msg-{uuid4()}"

    if route == "RELATED_ARTICLES":
        related_matches = await retrieve_related_articles(
            session,
            user_id=user.id,
            query=message,
            exclude_article_id=article_id,
            limit=5,
        )
        if related_matches:
            citations = [_serialize_related_match(match) for match in related_matches]
            return {
                "conversationId": next_conversation_id,
                "messageId": message_id,
                "route": route,
                "reply": _build_related_reply(citations),
                "citations": citations,
                "retrievalSnapshot": {
                    "route": route,
                    "query": message,
                    "articles": citations,
                },
            }
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "route": route,
            "reply": "没有找到明显相关的已导入文章。",
            "citations": [],
            "retrievalSnapshot": {
                "route": route,
                "query": message,
                "articles": [],
            },
        }

    if article_id:
        article = await repo_article.get_article(
            session,
            user_id=user.id,
            notebook_id=notebook_id,
            article_id=article_id,
        )
        if article is None:
            raise AppError(404, "未找到对应文章", code="article_not_found")
        excerpt = (article.clean_markdown or article.preview_markdown or "").strip()
        excerpt = excerpt[:280] if excerpt else "当前文章尚无可用正文。"
        citation = {
            "articleId": article.id,
            "title": article.title,
            "notebookId": article.notebook_id,
            "notebookTitle": notebook.title,
            "snippet": excerpt,
            "matchedBy": ["current_article"],
        }
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "route": route,
            "reply": f"我已加载当前文章《{article.title}》的内容上下文。你可以继续追问细节、摘要、观点，或直接问“还有没有类似资料”。",
            "citations": [citation],
            "retrievalSnapshot": {
                "route": route,
                "query": message,
                "articles": [citation],
            },
        }

    related_matches = await retrieve_related_articles(
        session,
        user_id=user.id,
        query=message,
        exclude_article_id=None,
        limit=3,
    )
    if not related_matches:
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "route": route,
            "reply": "当前还没有足够的文章上下文来回答这个问题。",
            "citations": [],
            "retrievalSnapshot": {
                "route": route,
                "query": message,
                "articles": [],
            },
        }
    citations = [_serialize_related_match(match) for match in related_matches]
    return {
        "conversationId": next_conversation_id,
        "messageId": message_id,
        "route": route,
        "reply": _build_related_reply(citations, fallback_label="我先为你找了一批可能相关的已导入文章。"),
        "citations": citations,
        "retrievalSnapshot": {
            "route": route,
            "query": message,
            "articles": citations,
        },
    }


def _serialize_related_match(match: RetrievedArticleMatch) -> dict:
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


def _build_related_reply(citations: list[dict], *, fallback_label: str | None = None) -> str:
    if not citations:
        return "没有找到明显相关的已导入文章。"
    label = fallback_label or "我找到了几篇可能相关的已导入文章，已经按综合相关性排好序。"
    top_titles = "、".join(citation["title"] for citation in citations[:3])
    return f"{label}\n\n优先可看：{top_titles}。你可以直接点下面的来源卡片继续查看或追问比较。"
