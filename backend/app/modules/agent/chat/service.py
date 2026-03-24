"""聊天服务：会话管理 + LangGraph / 流式编排。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import AsyncIterator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import (
    observe_chat_answer_length,
    observe_chat_e2e,
    observe_chat_error,
    observe_chat_retrieval,
    observe_chat_route_mix,
    observe_chat_token_cost,
)
from app.infra.telemetry.tracing import start_span
from app.modules.agent.chat import repo
from app.modules.agent.chat.nodes import (
    citation_verifier_node,
    query_router_node,
    retrieval_engine_node,
    retrieval_planner_node,
    web_search_broker_node,
)
from app.modules.agent.chat.prompts import (
    ANSWER_SYSTEMS,
    ANSWER_USER_GENERAL,
    ANSWER_USER_GROUNDED,
)
from app.modules.agent.chat.state import ChatGraphState, RetrievalPlanSpec
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
    conversation, notebook_title, article_title = await _prepare_context(
        db, user_id=user_id, notebook_id=notebook_id,
        question=question, article_id=article_id, conversation_id=conversation_id,
    )

    history = [
        {"role": msg.role, "content": msg.content}
        for msg in await repo.list_recent_messages(db, conversation_id=conversation.id, limit=6)
    ]

    state: dict = {
        "query": question,
        "notebook_id": notebook_id,
        "article_id": article_id,
        "user_id": user_id,
        "user": user,
        "notebook_title": notebook_title,
        "article_title": article_title,
        "history": history,
        "route": "general",
        "retrieval_scope": "none",
        "output_mode": "concise",
        "tools_needed": [],
        "retrieval_plan": RetrievalPlanSpec(),
        "local_evidence": [],
        "need_web_search": False,
        "web_search_reason": "not_needed",
        "web_evidence": [],
        "answer_text": "",
        "raw_citations": [],
        "verified_citations": [],
        "trace_log": {},
    }

    # ========== phase 3 运行前置节点 ==========
    try:
        with start_span("chat.agent", attributes={"chat.notebook_id": notebook_id}):
            state.update(await query_router_node(state))
            state.update(await retrieval_planner_node(state))

            plan: RetrievalPlanSpec = state.get("retrieval_plan", RetrievalPlanSpec())
            if plan.strategy != "skip":
                state.update(await retrieval_engine_node(state))

            state.update(await web_search_broker_node(state))
    except Exception as exc:
        logger.exception("chat.pre_answer_failed", error=str(exc))
        observe_chat_error(node="pre_answer")

    route = state.get("route", "general")

    # ========== phase 4 流式生成回答 ==========
    messages = _build_answer_messages(state)
    full_answer = ""

    try:
        async for chunk in model.astream(messages):
            token = chunk.content if hasattr(chunk, "content") else ""
            if token:
                full_answer += token
                yield {"type": "token", "text": token}
    except Exception as exc:
        logger.exception("chat.answer_stream_failed", error=str(exc)[:200])
        observe_chat_error(node="answer_generator")
        if not full_answer:
            full_answer = f"抱歉，生成回答时出错了：{str(exc)[:100]}"
            yield {"type": "token", "text": full_answer}

    observe_chat_answer_length(route=route, length=len(full_answer))

    # ========== phase 5 引用校验 ==========
    state["answer_text"] = full_answer
    state["raw_citations"] = _extract_citations(full_answer)

    try:
        state.update(await citation_verifier_node(state))
    except Exception as exc:
        logger.warning("chat.citation_verify_failed", error=str(exc)[:200])

    verified_citations = state.get("verified_citations", [])
    trace_log = state.get("trace_log", {})
    need_web_search = state.get("need_web_search", False)
    local_evidence = state.get("local_evidence", [])
    elapsed_ms = round((perf_counter() - t0) * 1000, 2)

    # ========== phase 6 持久化 ==========
    assistant_msg = await repo.append_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=full_answer,
        article_id=article_id,
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
    conversation = None
    if conversation_id:
        conversation = await repo.get_conversation(
            db, conversation_id=conversation_id, user_id=user_id,
        )
    if conversation is None:
        conversation = await repo.create_conversation(
            db,
            user_id=user_id,
            notebook_id=notebook_id,
            article_id=article_id,
            title=question[:80],
        )
        await db.flush()

    await repo.append_message(
        db, conversation_id=conversation.id, role="user",
        content=question, article_id=article_id,
    )

    notebook_title = ""
    article_title = ""
    notebook = await notebooks_repo.get_notebook(db, user_id=user_id, notebook_id=notebook_id)
    if notebook:
        notebook_title = notebook.title or ""
    if article_id:
        article = await notebooks_repo.get_article(
            db, user_id=user_id, notebook_id=notebook_id, article_id=article_id,
        )
        if article:
            article_title = article.title or ""

    return conversation, notebook_title, article_title


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
