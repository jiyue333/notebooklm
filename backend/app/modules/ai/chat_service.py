from __future__ import annotations

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.notebooks import repo as notebooks_repo
from app.modules.retrieval.article_retriever import retrieve_related_articles
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
        related_articles = await retrieve_related_articles(
            session,
            user_id=user.id,
            query=message,
            exclude_article_id=article_id,
            limit=5,
        )
        if related_articles:
            lines = ["我找到这些相关文章："]
            citations = []
            for index, article in enumerate(related_articles, start=1):
                lines.append(f"{index}. {article.title}")
                citations.append(
                    {
                        "articleId": article.id,
                        "title": article.title,
                        "notebookId": article.notebook_id,
                    }
                )
            return {
                "conversationId": next_conversation_id,
                "messageId": message_id,
                "reply": "\n".join(lines),
                "citations": citations,
            }
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "reply": "没有找到明显相关的已导入文章。",
            "citations": [],
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
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "reply": f"当前文章《{article.title}》的内容片段：\n\n{excerpt}",
            "citations": [
                {
                    "articleId": article.id,
                    "title": article.title,
                    "notebookId": article.notebook_id,
                }
            ],
        }

    related_articles = await retrieve_related_articles(
        session,
        user_id=user.id,
        query=message,
        exclude_article_id=None,
        limit=3,
    )
    if not related_articles:
        return {
            "conversationId": next_conversation_id,
            "messageId": message_id,
            "reply": "当前还没有足够的文章上下文来回答这个问题。",
            "citations": [],
        }
    return {
        "conversationId": next_conversation_id,
        "messageId": message_id,
        "reply": "我先基于你已导入的相关文章给出候选上下文。",
        "citations": [
            {
                "articleId": article.id,
                "title": article.title,
                "notebookId": article.notebook_id,
            }
            for article in related_articles
        ],
    }
