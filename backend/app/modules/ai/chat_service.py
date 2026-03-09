from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.ai.conversation_service import (
    append_assistant_message,
    append_user_message,
    load_history_messages,
    load_or_create_conversation,
    maybe_rollup_conversation,
)
from app.modules.ai.langchain_factory import build_chat_chain, get_user_generation_settings
from app.modules.notebooks import repo as notebooks_repo
from app.modules.retrieval.article_retriever import RetrievedArticleMatch, retrieve_related_articles
from app.modules.retrieval.router import route_chat_message
from app.modules.search import repo_article

CURRENT_ARTICLE_CONTEXT_LIMIT = 14000
RELATED_ARTICLE_CONTEXT_LIMIT = 2200

logger = structlog.get_logger(__name__)


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

    conversation = await load_or_create_conversation(
        session,
        user_id=user.id,
        notebook_id=notebook_id,
        conversation_id=conversation_id,
        article_id=article_id,
    )
    user_message = await append_user_message(
        session,
        conversation=conversation,
        article_id=article_id,
        content=message,
    )
    await session.commit()

    route = route_chat_message(message, article_id)
    context_block, citations = await _build_context_block(
        session,
        user=user,
        notebook=notebook,
        article_id=article_id,
        route=route,
        message=message,
    )
    history_messages = await load_history_messages(
        session,
        conversation_id=conversation.id,
        exclude_message_id=user_message.id,
    )

    model_settings = get_user_generation_settings(user)
    chain = build_chat_chain(user)
    answer = (
        await chain.ainvoke(
            {
                "output_language": model_settings["outputLanguage"],
                "notebook_title": notebook.title,
                "route": route,
                "rolling_summary": conversation.rolling_summary or "暂无会话摘要。",
                "context_block": context_block,
                "history_messages": history_messages,
                "user_message": message,
            }
        )
    ).strip()
    if not answer:
        raise AppError(502, "对话生成失败", code="chat_generation_failed")

    retrieval_snapshot = {
        "route": route,
        "query": message,
        "articles": citations,
    }
    assistant_message = await append_assistant_message(
        session,
        conversation=conversation,
        article_id=article_id,
        route=route,
        content=answer,
        retrieval_snapshot=retrieval_snapshot,
    )
    try:
        await maybe_rollup_conversation(session, conversation=conversation, user=user)
    except Exception as exc:
        logger.exception(
            "chat.rollup_failed",
            conversation_id=conversation.id,
            error=str(exc),
        )
    await session.commit()
    return {
        "conversationId": conversation.id,
        "messageId": assistant_message.id,
        "route": route,
        "reply": answer,
        "citations": citations,
        "retrievalSnapshot": retrieval_snapshot,
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


async def _build_context_block(
    session: AsyncSession,
    *,
    user,
    notebook,
    article_id: str | None,
    route: str,
    message: str,
) -> tuple[str, list[dict]]:
    if route in {"CURRENT_ARTICLE", "EVIDENCE_LOOKUP"} and article_id:
        article = await repo_article.get_article(
            session,
            user_id=user.id,
            notebook_id=notebook.id,
            article_id=article_id,
        )
        if article is None:
            raise AppError(404, "未找到对应文章", code="article_not_found")
        if not article.clean_markdown:
            raise AppError(409, "文章正文尚未准备完成", code="article_not_ready")

        snippet = (article.clean_markdown or "").strip()[:320]
        citation = {
            "articleId": article.id,
            "title": article.title,
            "notebookId": article.notebook_id,
            "notebookTitle": notebook.title,
            "snippet": snippet,
            "matchedBy": ["current_article"],
        }
        return (
            "\n\n".join(
                [
                    f"当前文章：{article.title}",
                    f"文章摘要片段：{snippet}",
                    f"文章正文：{article.clean_markdown[:CURRENT_ARTICLE_CONTEXT_LIMIT]}",
                ]
            ),
            [citation],
        )

    related_matches = await retrieve_related_articles(
        session,
        user_id=user.id,
        query=message,
        exclude_article_id=article_id if route == "RELATED_ARTICLES" else None,
        limit=5 if route == "RELATED_ARTICLES" else 3,
    )
    citations = [_serialize_related_match(match) for match in related_matches]
    if not citations:
        return (
            "当前没有找到足够相关的已导入文章。请明确说明你想讨论的主题，或者先导入更多来源。",
            [],
        )

    context_sections = []
    for match in related_matches[:3]:
        article = match.article
        notebook_title = getattr(getattr(article, "notebook", None), "title", notebook.title)
        article_context = (article.clean_markdown or article.article_retrieval_text or article.preview_markdown or "")
        context_sections.append(
            "\n".join(
                [
                    f"文章标题：{article.title}",
                    f"所在笔记本：{notebook_title}",
                    f"命中方式：{', '.join(match.matched_by)}",
                    f"相关片段：{match.snippet}",
                    f"上下文：{article_context[:RELATED_ARTICLE_CONTEXT_LIMIT]}",
                ]
            )
        )
    return "\n\n---\n\n".join(context_sections), citations
