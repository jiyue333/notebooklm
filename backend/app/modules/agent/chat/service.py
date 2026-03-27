"""聊天服务：会话管理 + LangGraph / 流式编排。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import AsyncIterator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import (
    observe_chat_answer_length,
    observe_chat_e2e,
    observe_chat_retrieval,
    observe_chat_route_mix,
)
from app.modules.agent.chat import repo
from app.modules.agent.chat.graph import get_chat_graph
from app.modules.agent.chat.prompts import (
    ANSWER_SYSTEMS,
    ANSWER_USER_GENERAL,
    ANSWER_USER_GROUNDED,
)
from app.modules.notebooks import repo as notebooks_repo

logger = structlog.get_logger(__name__)

_ROUTE_BADGES = {
    "article_qa": "From this article",
    "notebook_search": "From your notebooks",
    "recommendation": "Recommended reading",
    "general": "General answer",
}


# ========== 流式接口 ==========

async def stream_message(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    question: str,
    article_id: str | None = None,
    conversation_id: str | None = None,
    user=None,
) -> AsyncIterator[dict]:
    """流式聊天：逐 token yield，最后 yield done 事件。

    Yields:
        {"type": "token", "text": "..."}
        {"type": "done", "data": {...}}
    """

    t0 = perf_counter()

    # ========== phase 1 初始化 ==========
    model = build_user_chat_model(user) if user else None
    if model is None:
        yield {"type": "done", "data": _error_done("model_not_configured")}
        return

    # ========== phase 2 加载会话与上下文 ==========
    conversation, notebook_title, article_title, resolved_article_id = await _prepare_context(
        db, user_id=user_id, notebook_id=notebook_id,
        question=question, article_id=article_id, conversation_id=conversation_id,
    )

    history = [
        {"role": msg.role, "content": msg.content}
        for msg in await repo.list_recent_messages(db, conversation_id=conversation.id, limit=6)
    ]

    graph = get_chat_graph()
    state = await graph.ainvoke({
        "query": question,
        "notebook_id": notebook_id,
        "article_id": resolved_article_id,
        "user_id": user_id,
        "user": user,
        "notebook_title": notebook_title,
        "article_title": article_title,
        "history": history,
        "route": "general",
        "retrieval_scope": "none",
        "output_mode": "concise",
        "tools_needed": [],
        "retrieval_plan": None,
        "local_evidence": [],
        "need_web_search": False,
        "web_search_reason": "not_needed",
        "web_evidence": [],
        "answer_text": "",
        "raw_citations": [],
        "verified_citations": [],
        "trace_log": {},
    })

    route = state.get("route", "general")

    full_answer = state.get("answer_text", "")
    for chunk in [full_answer[i:i + 48] for i in range(0, len(full_answer), 48)]:
        if chunk:
            yield {"type": "token", "text": chunk}

    verified_citations = state.get("verified_citations", [])
    trace_log = state.get("trace_log", {})
    need_web_search = state.get("need_web_search", False)
    local_evidence = state.get("local_evidence", [])
    elapsed_ms = round((perf_counter() - t0) * 1000, 2)
    observe_chat_answer_length(route=route, length=len(full_answer))

    # ========== phase 6 持久化 ==========
    assistant_msg = await repo.append_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=full_answer,
        article_id=resolved_article_id,
        route=route,
        retrieval_snapshot_json={"evidence": verified_citations, "trace_log": trace_log},
        web_searched=need_web_search,
        retrieval_count=len(local_evidence),
        citation_count=len(verified_citations),
        latency_ms=elapsed_ms,
    )
    await db.commit()

    # ========== phase 7 指标 ==========
    observe_chat_e2e(duration_ms=elapsed_ms)
    observe_chat_route_mix(route=route)
    observe_chat_retrieval(route=route, evidence_count=len(local_evidence), recommendation_count=0)
    logger.info(
        "chat.completed", route=route, conversation_id=conversation.id,
        elapsed_ms=elapsed_ms, web_searched=need_web_search, citations=len(verified_citations),
    )

    yield {
        "type": "done",
        "data": {
            "route": route,
            "routeBadge": _ROUTE_BADGES.get(route, "General answer"),
            "answer": full_answer,
            "evidence": verified_citations,
            "conversationId": conversation.id,
            "messageId": assistant_msg.id,
            "webSearched": need_web_search,
        },
    }


# ========== 非流式接口（向后兼容） ==========

async def send_message(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    question: str,
    article_id: str | None = None,
    conversation_id: str | None = None,
    user=None,
    **_kwargs,
) -> dict:
    result: dict = {}
    async for event in stream_message(
        db,
        user_id=user_id,
        notebook_id=notebook_id,
        question=question,
        article_id=article_id,
        conversation_id=conversation_id,
        user=user,
    ):
        if event["type"] == "done":
            result = event["data"]
    return result


# ── 内部工具函数 ──────────────────────────────────────────────────

async def _prepare_context(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    question: str,
    article_id: str | None,
    conversation_id: str | None,
):
    notebook = await notebooks_repo.get_notebook(db, user_id=user_id, notebook_id=notebook_id)
    if notebook is None:
        raise AppError(404, "未找到对应的笔记本", code="notebook_not_found")

    conversation = None
    if conversation_id:
        conversation = await repo.get_conversation(
            db, conversation_id=conversation_id, user_id=user_id,
        )
        if conversation is None or conversation.notebook_id != notebook_id:
            raise AppError(404, "未找到对应会话", code="conversation_not_found")
    if conversation is None:
        conversation = await repo.create_conversation(
            db,
            user_id=user_id,
            notebook_id=notebook_id,
            article_id=article_id,
            title=question[:80],
        )
        await db.flush()

    resolved_article_id = article_id or conversation.current_article_id
    article_title = ""
    if resolved_article_id:
        article = await notebooks_repo.get_article(
            db,
            user_id=user_id,
            notebook_id=notebook_id,
            article_id=resolved_article_id,
        )
        if article is None:
            raise AppError(404, "未找到对应文章", code="article_not_found")
        article_title = article.title or ""

    await repo.append_message(
        db, conversation_id=conversation.id, role="user",
        content=question, article_id=resolved_article_id,
    )

    notebook_title = notebook.title or ""

    return conversation, notebook_title, article_title, resolved_article_id


def _build_answer_messages(state: dict) -> list:
    """根据 route 构建 answer LLM 的 messages。"""
    route = state.get("route", "general")
    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])
    history = state.get("history", [])

    system = ANSWER_SYSTEMS.get(route, ANSWER_SYSTEMS["general"])
    history_text = _format_history(history)

    if route == "general":
        evidence_parts: list[str] = []
        local_text = _format_evidence(local_evidence, "local")
        web_text = _format_evidence(web_evidence, "web")
        if local_text:
            evidence_parts.append(local_text)
        if web_text:
            evidence_parts.append(web_text)

        user_msg = ANSWER_USER_GENERAL.format(
            history_text=history_text or "(无历史对话)",
            evidence_text="\n\n".join(evidence_parts) if evidence_parts else "(无)",
            query=state["query"],
        )
    else:
        user_msg = ANSWER_USER_GROUNDED.format(
            output_mode=state.get("output_mode", "concise"),
            local_evidence_text=_format_evidence(local_evidence, "local") or "(无本地证据)",
            web_evidence_text=_format_evidence(web_evidence, "web") or "(无网络证据)",
            history_text=history_text or "(无历史对话)",
            query=state["query"],
        )

    return [SystemMessage(content=system), HumanMessage(content=user_msg)]


def _format_evidence(evidence: list[dict], kind: str) -> str:
    if not evidence:
        return ""
    lines: list[str] = []
    for i, e in enumerate(evidence, 1):
        if kind == "web":
            lines.append(f"[W{i}] {e.get('title', '')} ({e.get('url', '')}): {e.get('snippet', '')[:300]}")
        else:
            heading = e.get("heading_title") or e.get("section_path") or ""
            title = e.get("article_title", "")
            prefix = f"{title} > {heading}" if heading else title
            lines.append(f"[{i}] {prefix}: {e.get('raw_text', '')[:400]}")
    return "\n\n".join(lines)


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    return "\n".join(
        f"{t.get('role', 'user')}: {t.get('content', '')[:300]}" for t in history[-4:]
    )


def _extract_citations(text: str) -> list[dict]:
    citations: list[dict] = []
    for m in re.finditer(r"\[(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "local"})
    for m in re.finditer(r"\[W(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "web"})
    return citations


def _error_done(code: str) -> dict:
    return {
        "route": "general",
        "routeBadge": "General answer",
        "answer": "",
        "evidence": [],
        "error": code,
    }


def build_conversation_view(conversation, messages: list[dict] | None = None) -> dict:
    return {
        'id': conversation.id,
        'title': conversation.title or '新对话',
        'currentArticleId': conversation.current_article_id,
        'updatedAt': conversation.updated_at.isoformat() if conversation.updated_at else None,
        'lastMessageAt': conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        'messages': messages or [],
    }


async def list_notebook_conversations(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> list[dict]:
    conversations = await repo.list_conversations(db, user_id=user_id, notebook_id=notebook_id)
    items: list[dict] = []
    for conversation in conversations:
        recent_messages = await repo.list_recent_messages(db, conversation_id=conversation.id, limit=12)
        items.append(build_conversation_view(
            conversation,
            messages=[{
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'route': message.route,
                'createdAt': message.created_at.isoformat(),
            } for message in recent_messages],
        ))
    return items


async def remove_notebook_conversation(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    conversation_id: str,
) -> None:
    conversation = await repo.get_conversation(db, conversation_id=conversation_id, user_id=user_id)
    if conversation is None or conversation.notebook_id != notebook_id:
        raise ValueError('conversation_not_found')
    await repo.delete_conversation(db, conversation_id=conversation_id, user_id=user_id)
    await db.commit()
