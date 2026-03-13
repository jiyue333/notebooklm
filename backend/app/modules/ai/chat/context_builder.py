from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.ai.chat_models import get_user_generation_settings, require_user_chat_model
from app.infra.telemetry.context import bind_observability_context
from app.infra.telemetry.metrics import observe_ai_retrieval_context, observe_ai_route
from app.infra.telemetry.tracing import start_span, traced
from app.modules.ai.chat.conversation import (
    append_user_message,
    load_history_messages,
    load_or_create_conversation,
)
from app.modules.ai.chat.result_serializer import serialize_chunk_match, serialize_related_match
from app.modules.ai.prompts.chat_prompt import build_chat_prompt
from app.modules.notebooks import repo as notebooks_repo
from app.modules.retrieval.article_retriever import retrieve_related_articles
from app.modules.retrieval.chunk_retriever import retrieve_notebook_evidence_chunks
from app.modules.retrieval.router import route_chat_message
from app.modules.search.articles import repo as repo_article

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.prompt_values import PromptValue

    from app.modules.ai.chat.models import Conversation, ConversationMessage
    from app.modules.auth.models import User
    from app.modules.notebooks.models import Notebook

CURRENT_ARTICLE_CONTEXT_LIMIT = 2000
RELATED_ARTICLE_CONTEXT_LIMIT = 1000

_EMPTY_RETRIEVAL: dict = {"articles": [], "chunks": []}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ContextBlock:
    """build_context_block 的结构化返回值，替代原来的裸 tuple。"""

    text: str
    citations: list[dict] = field(default_factory=list)
    retrieval_details: dict = field(default_factory=dict)


@dataclass(slots=True)
class PreparedChatReply:
    user: User
    conversation: Conversation
    user_message: ConversationMessage
    route: str
    route_reason: str
    route_confidence: float
    citations: list[dict]
    retrieval_details: dict
    model_settings: dict
    trace_metadata: dict
    messages: PromptValue
    model: BaseChatModel


# ---------------------------------------------------------------------------
# Public: prepare_chat_reply
# ---------------------------------------------------------------------------

async def prepare_chat_reply(
    session: AsyncSession,
    *,
    user: User,
    notebook_id: str,
    conversation_id: str | None,
    article_id: str | None,
    message: str,
) -> PreparedChatReply:
    with start_span(
        "chat.prepare",
        attributes={
            "notebook_id": notebook_id,
            "article_id": article_id,
        },
    ):
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
        history_messages = await load_history_messages(
            session,
            conversation_id=conversation.id,
            exclude_message_id=user_message.id,
        )

    with start_span(
        "chat.route",
        attributes={
            "notebook_id": notebook.id,
            "article_id": article_id,
        },
    ):
        route_decision = await route_chat_message(
            user=user,
            notebook_title=notebook.title,
            article_id=article_id,
            message=message,
        )
    observe_ai_route(operation="chat", route=route_decision.route)

    ctx = await build_context_block(
        session,
        user=user,
        notebook=notebook,
        article_id=article_id,
        route=route_decision.route,
        message=message,
    )
    for ctx_type in ("articles", "chunks"):
        observe_ai_retrieval_context(
            operation="chat",
            route=route_decision.route,
            context_type=ctx_type,
            count=len(ctx.retrieval_details.get(ctx_type, [])),
        )

    model_settings = get_user_generation_settings(user)
    trace_metadata = _build_trace_metadata(
        user=user,
        notebook_id=notebook.id,
        article_id=article_id,
        conversation_id=conversation.id,
        model_settings=model_settings,
        route=route_decision.route,
        route_reason=route_decision.reason,
    )
    bind_observability_context(
        user_id=user.id,
        notebook_id=notebook.id,
        article_id=article_id,
        conversation_id=conversation.id,
        provider=model_settings["modelProvider"],
        model_name=model_settings["modelName"],
    )
    with start_span(
        "chat.prompt_build",
        attributes={
            "route": route_decision.route,
            "provider": model_settings["modelProvider"],
            "model_name": model_settings["modelName"],
        },
    ):
        prompt = build_chat_prompt()
        model = require_user_chat_model(user)
        messages = await prompt.ainvoke(
            {
                "output_language": model_settings["outputLanguage"],
                "notebook_title": notebook.title,
                "route": route_decision.route,
                "rolling_summary": conversation.rolling_summary or "暂无会话摘要。",
                "context_block": ctx.text,
                "history_messages": history_messages,
                "user_message": message,
            },
            config={"run_name": "chat_prompt", "metadata": trace_metadata},
        )
    return PreparedChatReply(
        user=user,
        conversation=conversation,
        user_message=user_message,
        route=route_decision.route,
        route_reason=route_decision.reason,
        route_confidence=route_decision.confidence,
        citations=ctx.citations,
        retrieval_details=ctx.retrieval_details,
        model_settings=model_settings,
        trace_metadata=trace_metadata,
        messages=messages,
        model=model,
    )


# ---------------------------------------------------------------------------
# Public: build_context_block — 路由分发
# ---------------------------------------------------------------------------

@traced("chat.retrieval")
async def build_context_block(
    session: AsyncSession,
    *,
    user: User,
    notebook: Notebook,
    article_id: str | None,
    route: str,
    message: str,
) -> ContextBlock:
    """根据路由类型构建上下文，分发给对应的子函数。"""
    builder = _CONTEXT_BUILDERS.get(route, _build_related_articles_context)
    return await builder(session, user=user, notebook=notebook, article_id=article_id, message=message)


# ---------------------------------------------------------------------------
# Private: 每个路由的上下文构建器
# ---------------------------------------------------------------------------

async def _build_current_article_context(
    session: AsyncSession,
    *,
    user: User,
    notebook: Notebook,
    article_id: str | None,
    message: str,
) -> ContextBlock:
    """CURRENT_ARTICLE 路由：基于当前打开的文章构建上下文。"""
    if not article_id:
        return await _build_related_articles_context(
            session, user=user, notebook=notebook, article_id=article_id, message=message,
        )

    article = await repo_article.get_article(
        session, user_id=user.id, notebook_id=notebook.id, article_id=article_id,
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
    text = "\n\n".join([
        f"当前文章：{article.title}",
        f"文章摘要片段：{snippet}",
        f"文章正文：{article.clean_markdown[:CURRENT_ARTICLE_CONTEXT_LIMIT]}",
    ])
    return ContextBlock(
        text=text,
        citations=[citation],
        retrieval_details={"articles": [citation], "chunks": []},
    )


async def _build_general_context(
    session: AsyncSession,
    *,
    user: User,
    notebook: Notebook,
    article_id: str | None,
    message: str,
) -> ContextBlock:
    """GENERAL 路由：通用问题，无需深度检索。"""
    current_article_title = None
    if article_id:
        article = await repo_article.get_article(
            session, user_id=user.id, notebook_id=notebook.id, article_id=article_id,
        )
        current_article_title = article.title if article is not None else None

    text = "\n".join([
        f"当前笔记本：{notebook.title}",
        f"当前打开文章：{current_article_title or '无'}",
        "路由说明：这是通用问题，不需要基于当前文章正文或 notebook 证据检索来回答。",
        "回答要求：直接回答用户问题即可；如果用户实际上需要基于文章或证据作答，应明确提示对方改问更具体的问题。",
    ])
    return ContextBlock(text=text, retrieval_details=_EMPTY_RETRIEVAL)


async def _build_evidence_lookup_context(
    session: AsyncSession,
    *,
    user: User,
    notebook: Notebook,
    article_id: str | None,
    message: str,
) -> ContextBlock:
    """EVIDENCE_LOOKUP 路由：优先 chunk 检索，fallback 到文章级检索。"""
    # 1. 尝试 chunk 级检索
    chunk_matches = await retrieve_notebook_evidence_chunks(
        session, user_id=user.id, notebook_id=notebook.id, query=message, limit=5,
    )
    chunk_citations = [
        serialize_chunk_match(match, notebook_title=notebook.title)
        for match in chunk_matches
    ]
    if chunk_citations:
        return _format_chunk_context(chunk_matches, chunk_citations, notebook_title=notebook.title)

    # 2. Fallback: 文章级检索
    notebook_matches = await retrieve_related_articles(
        session, user_id=user.id, query=message, notebook_id=notebook.id, limit=3,
    )
    notebook_citations = [serialize_related_match(m) for m in notebook_matches]
    if not notebook_citations:
        return ContextBlock(
            text="当前 notebook 里没有找到足够相关的证据文章。请换一种问法，或者先导入更多来源。",
            retrieval_details=_EMPTY_RETRIEVAL,
        )

    text = _format_article_sections(notebook_matches[:3], notebook_title=notebook.title)
    return ContextBlock(
        text=text,
        citations=notebook_citations,
        retrieval_details={"articles": notebook_citations, "chunks": []},
    )


async def _build_related_articles_context(
    session: AsyncSession,
    *,
    user: User,
    notebook: Notebook,
    article_id: str | None,
    message: str,
) -> ContextBlock:
    """RELATED_ARTICLES（及默认）路由：跨文章检索。"""
    related_matches = await retrieve_related_articles(
        session,
        user_id=user.id,
        query=message,
        exclude_article_id=article_id,
        limit=5,
    )
    citations = [serialize_related_match(m) for m in related_matches]
    if not citations:
        return ContextBlock(
            text="当前没有找到足够相关的已导入文章。请明确说明你想讨论的主题，或者先导入更多来源。",
            retrieval_details=_EMPTY_RETRIEVAL,
        )

    sections: list[str] = []
    for match in related_matches[:3]:
        article = match.article
        nb_title = getattr(getattr(article, "notebook", None), "title", notebook.title)
        article_context = (
            article.clean_markdown or article.article_retrieval_text or article.preview_markdown or ""
        )
        sections.append("\n".join([
            f"文章标题：{article.title}",
            f"所在笔记本：{nb_title}",
            f"命中方式：{', '.join(match.matched_by)}",
            f"相关片段：{match.snippet}",
            f"上下文：{article_context[:RELATED_ARTICLE_CONTEXT_LIMIT]}",
        ]))
    return ContextBlock(
        text="\n\n---\n\n".join(sections),
        citations=citations,
        retrieval_details={"articles": citations, "chunks": []},
    )


# 路由 → 构建器映射表
_CONTEXT_BUILDERS = {
    "CURRENT_ARTICLE": _build_current_article_context,
    "GENERAL": _build_general_context,
    "EVIDENCE_LOOKUP": _build_evidence_lookup_context,
    "RELATED_ARTICLES": _build_related_articles_context,
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _format_chunk_context(
    chunk_matches: list,
    chunk_citations: list[dict],
    *,
    notebook_title: str,
) -> ContextBlock:
    """将 chunk 检索结果格式化为 ContextBlock。"""
    article_citations: list[dict] = []
    seen_article_ids: set[str] = set()
    for match in chunk_matches:
        if match.article.id in seen_article_ids:
            continue
        seen_article_ids.add(match.article.id)
        article_citations.append({
            "articleId": match.article.id,
            "title": match.article.title,
            "notebookId": match.article.notebook_id,
            "notebookTitle": notebook_title,
            "snippet": match.snippet,
            "matchedBy": match.matched_by,
        })

    sections = [
        "\n".join([
            f"文章标题：{m.article.title}",
            f"章节：{m.chunk.heading_title or m.chunk.section_path or '未标注章节'}",
            f"命中方式：{', '.join(m.matched_by)}",
            f"证据片段：{m.snippet}",
            f"完整 chunk：{m.chunk.chunk_text}",
        ])
        for m in chunk_matches
    ]
    return ContextBlock(
        text="\n\n---\n\n".join(sections),
        citations=chunk_citations,
        retrieval_details={"articles": article_citations, "chunks": chunk_citations},
    )


def _format_article_sections(matches: list, *, notebook_title: str) -> str:
    """将文章级检索结果格式化为上下文文本。"""
    sections: list[str] = []
    for match in matches:
        article = match.article
        article_context = (
            article.clean_markdown or article.article_retrieval_text or article.preview_markdown or ""
        )
        sections.append("\n".join([
            f"文章标题：{article.title}",
            f"命中方式：{', '.join(match.matched_by)}",
            f"相关片段：{match.snippet}",
            f"上下文：{article_context[:RELATED_ARTICLE_CONTEXT_LIMIT]}",
        ]))
    return "\n\n---\n\n".join(sections)


def _build_trace_metadata(
    *,
    user: User,
    notebook_id: str,
    article_id: str | None = None,
    conversation_id: str | None = None,
    model_settings: dict,
    route: str | None = None,
    route_reason: str | None = None,
) -> dict:
    """构建通用的 trace_metadata 字典，消除各处重复。"""
    meta: dict = {
        "user_id": user.id,
        "notebook_id": notebook_id,
        "provider": model_settings["modelProvider"],
        "model_name": model_settings["modelName"],
    }
    if article_id is not None:
        meta["article_id"] = article_id
    if conversation_id is not None:
        meta["conversation_id"] = conversation_id
    if route is not None:
        meta["route"] = route
    if route_reason is not None:
        meta["route_reason"] = route_reason
    return meta
