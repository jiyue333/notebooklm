from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call
from app.modules.ai.conversation_service import (
    append_assistant_message,
    append_user_message,
    load_history_messages,
    load_or_create_conversation,
    maybe_rollup_conversation,
)
from app.modules.ai.langchain_factory import (
    build_chat_prompt,
    get_user_generation_settings,
    require_user_chat_model,
)
from app.modules.ai.streaming import encode_sse_event, extract_stream_text
from app.modules.notebooks import repo as notebooks_repo
from app.modules.retrieval.article_retriever import RetrievedArticleMatch, retrieve_related_articles
from app.modules.retrieval.chunk_retriever import RetrievedChunkMatch, retrieve_notebook_evidence_chunks
from app.modules.retrieval.router import route_chat_message
from app.modules.search import repo_article

CURRENT_ARTICLE_CONTEXT_LIMIT = 2000
RELATED_ARTICLE_CONTEXT_LIMIT = 1000

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PreparedChatReply:
    user: object
    conversation: object
    user_message: object
    route: str
    route_reason: str
    route_confidence: float
    citations: list[dict]
    retrieval_details: dict
    model_settings: dict
    trace_metadata: dict
    messages: list
    model: object


async def reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
) -> dict:
    prepared = await _prepare_chat_reply(
        session,
        user=user,
        notebook_id=notebook_id,
        conversation_id=conversation_id,
        article_id=article_id,
        message=message,
    )
    started_at = perf_counter()
    try:
        result = await prepared.model.ainvoke(
            prepared.messages,
            config={"run_name": "chat_model", "metadata": prepared.trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="chat",
            provider=prepared.model_settings["modelProvider"],
            model=prepared.model_settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    answer, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="chat",
        provider=prepared.model_settings["modelProvider"],
        model=prepared.model_settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    if not answer:
        raise AppError(502, "对话生成失败", code="chat_generation_failed")

    return await _finalize_chat_reply(session, prepared=prepared, answer=answer)


async def stream_reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
):
    prepared = await _prepare_chat_reply(
        session,
        user=user,
        notebook_id=notebook_id,
        conversation_id=conversation_id,
        article_id=article_id,
        message=message,
    )

    async def event_stream():
        started_at = perf_counter()
        answer_parts: list[str] = []
        try:
            yield encode_sse_event(
                "start",
                {
                    "conversationId": prepared.conversation.id,
                    "route": prepared.route,
                },
            )
            async for chunk in prepared.model.astream(
                prepared.messages,
                config={"run_name": "chat_model", "metadata": prepared.trace_metadata},
            ):
                text = extract_stream_text(chunk)
                if not text:
                    continue
                answer_parts.append(text)
                yield encode_sse_event("token", {"content": text})

            answer = "".join(answer_parts).strip()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="success",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            if not answer:
                raise AppError(502, "对话生成失败", code="chat_generation_failed")

            result = await _finalize_chat_reply(session, prepared=prepared, answer=answer)
            yield encode_sse_event("done", result)
        except AppError as exc:
            await session.rollback()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="error",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            yield encode_sse_event(
                "error",
                {
                    "message": exc.message,
                    "code": exc.code,
                    "status": exc.status_code,
                    "meta": exc.meta,
                },
            )
        except Exception as exc:
            await session.rollback()
            observe_llm_call(
                operation="chat",
                provider=prepared.model_settings["modelProvider"],
                model=prepared.model_settings["modelName"],
                status="error",
                duration_ms=round((perf_counter() - started_at) * 1000, 2),
            )
            logger.exception(
                "chat.stream_failed",
                conversation_id=prepared.conversation.id,
                error=str(exc),
            )
            yield encode_sse_event(
                "error",
                {
                    "message": "对话生成失败，请稍后重试",
                    "code": "chat_generation_failed",
                    "status": 502,
                    "meta": {},
                },
            )

    return event_stream()


async def _prepare_chat_reply(
    session: AsyncSession,
    *,
    user,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
) -> PreparedChatReply:
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

    route_decision = await route_chat_message(
        user=user,
        notebook_title=notebook.title,
        article_id=article_id,
        message=message,
    )
    route = route_decision.route
    context_block, citations, retrieval_details = await _build_context_block(
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
    trace_metadata = {
        "user_id": user.id,
        "notebook_id": notebook.id,
        "article_id": article_id,
        "conversation_id": conversation.id,
        "provider": model_settings["modelProvider"],
        "model_name": model_settings["modelName"],
        "route": route,
        "route_reason": route_decision.reason,
    }
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook.id,
        article_id=article_id,
        conversation_id=conversation.id,
        provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
    )
    prompt = build_chat_prompt()
    model = require_user_chat_model(user)
    messages = await prompt.ainvoke(
        {
            "output_language": model_settings["outputLanguage"],
            "notebook_title": notebook.title,
            "route": route,
            "rolling_summary": conversation.rolling_summary or "暂无会话摘要。",
            "context_block": context_block,
            "history_messages": history_messages,
            "user_message": message,
        },
        config={"run_name": "chat_prompt", "metadata": trace_metadata},
    )
    return PreparedChatReply(
        user=user,
        conversation=conversation,
        user_message=user_message,
        route=route,
        route_reason=route_decision.reason,
        route_confidence=route_decision.confidence,
        citations=citations,
        retrieval_details=retrieval_details,
        model_settings=model_settings,
        trace_metadata=trace_metadata,
        messages=messages,
        model=model,
    )


async def _finalize_chat_reply(
    session: AsyncSession,
    *,
    prepared: PreparedChatReply,
    answer: str,
) -> dict:
    retrieval_snapshot = {
        "route": prepared.route,
        "routeReason": prepared.route_reason,
        "routeConfidence": prepared.route_confidence,
        "query": prepared.user_message.content,
        **prepared.retrieval_details,
    }
    assistant_message = await append_assistant_message(
        session,
        conversation=prepared.conversation,
        article_id=prepared.user_message.article_id,
        route=prepared.route,
        content=answer,
        retrieval_snapshot=retrieval_snapshot,
    )
    try:
        await maybe_rollup_conversation(session, conversation=prepared.conversation, user=prepared.user)
    except Exception as exc:
        logger.exception(
            "chat.rollup_failed",
            conversation_id=prepared.conversation.id,
            error=str(exc),
        )
    await session.commit()
    return {
        "conversationId": prepared.conversation.id,
        "messageId": assistant_message.id,
        "route": prepared.route,
        "reply": answer,
        "citations": prepared.citations,
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


def _serialize_chunk_match(match: RetrievedChunkMatch, *, notebook_title: str) -> dict:
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


async def _build_context_block(
    session: AsyncSession,
    *,
    user,
    notebook,
    article_id: str | None,
    route: str,
    message: str,
) -> tuple[str, list[dict], dict]:
    if route == "CURRENT_ARTICLE" and article_id:
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
            {"articles": [citation], "chunks": []},
        )

    if route == "GENERAL":
        current_article_title = None
        if article_id:
            article = await repo_article.get_article(
                session,
                user_id=user.id,
                notebook_id=notebook.id,
                article_id=article_id,
            )
            current_article_title = article.title if article is not None else None
        context_lines = [
            f"当前笔记本：{notebook.title}",
            f"当前打开文章：{current_article_title or '无'}",
            "路由说明：这是通用问题，不需要基于当前文章正文或 notebook 证据检索来回答。",
            "回答要求：直接回答用户问题即可；如果用户实际上需要基于文章或证据作答，应明确提示对方改问更具体的问题。",
        ]
        return "\n".join(context_lines), [], {"articles": [], "chunks": []}

    if route == "EVIDENCE_LOOKUP":
        chunk_matches = await retrieve_notebook_evidence_chunks(
            session,
            user_id=user.id,
            notebook_id=notebook.id,
            query=message,
            limit=5,
        )
        chunk_citations = [_serialize_chunk_match(match, notebook_title=notebook.title) for match in chunk_matches]
        if chunk_citations:
            article_citations = []
            seen_article_ids: set[str] = set()
            for match in chunk_matches:
                if match.article.id in seen_article_ids:
                    continue
                seen_article_ids.add(match.article.id)
                article_citations.append(
                    {
                        "articleId": match.article.id,
                        "title": match.article.title,
                        "notebookId": match.article.notebook_id,
                        "notebookTitle": notebook.title,
                        "snippet": match.snippet,
                        "matchedBy": ["chunk_evidence"],
                    }
                )
            context_sections = []
            for match in chunk_matches:
                context_sections.append(
                    "\n".join(
                        [
                            f"文章标题：{match.article.title}",
                            f"章节：{match.chunk.heading_title or match.chunk.section_path or '未标注章节'}",
                            f"命中方式：{', '.join(match.matched_by)}",
                            f"证据片段：{match.snippet}",
                            f"完整 chunk：{match.chunk.chunk_text}",
                        ]
                    )
                )
            return (
                "\n\n---\n\n".join(context_sections),
                chunk_citations,
                {"articles": article_citations, "chunks": chunk_citations},
            )

        notebook_matches = await retrieve_related_articles(
            session,
            user_id=user.id,
            query=message,
            notebook_id=notebook.id,
            limit=3,
        )
        notebook_citations = [_serialize_related_match(match) for match in notebook_matches]
        if not notebook_citations:
            return (
                "当前 notebook 里没有找到足够相关的证据文章。请换一种问法，或者先导入更多来源。",
                [],
                {"articles": [], "chunks": []},
            )

        fallback_sections = []
        for match in notebook_matches[:3]:
            article = match.article
            article_context = (article.clean_markdown or article.article_retrieval_text or article.preview_markdown or "")
            fallback_sections.append(
                "\n".join(
                    [
                        f"文章标题：{article.title}",
                        f"命中方式：{', '.join(match.matched_by)}",
                        f"相关片段：{match.snippet}",
                        f"上下文：{article_context[:RELATED_ARTICLE_CONTEXT_LIMIT]}",
                    ]
                )
            )
        return (
            "\n\n---\n\n".join(fallback_sections),
            notebook_citations,
            {"articles": notebook_citations, "chunks": []},
        )

    related_matches = await retrieve_related_articles(
        session,
        user_id=user.id,
        query=message,
        exclude_article_id=article_id if route == "RELATED_ARTICLES" else None,
        limit=5,
    )
    citations = [_serialize_related_match(match) for match in related_matches]
    if not citations:
        return (
            "当前没有找到足够相关的已导入文章。请明确说明你想讨论的主题，或者先导入更多来源。",
            [],
            {"articles": [], "chunks": []},
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
    return "\n\n---\n\n".join(context_sections), citations, {"articles": citations, "chunks": []}
