"""聊天服务：会话管理 + LangGraph / 流式编排。"""

from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import AsyncIterator

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.ai.lite_models import build_lite_llm
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
from app.modules.settings.runtime import get_merged_user_settings
from app.modules.notebooks.models import Article

logger = structlog.get_logger(__name__)

_ROUTE_BADGES = {
    "article_qa": "From this article",
    "notebook_search": "From your notebooks",
    "recommendation": "Recommended reading",
    "general": "General answer",
}
_AUTO_CONVERSATION_TITLE_MAX_LEN = 40
_AUTO_CONVERSATION_TITLE_TIMEOUT_SECONDS = 4.0
_AUTO_CONVERSATION_TITLE_AWAIT_SECONDS = 2.5


# ========== 流式接口 ==========

async def stream_message(
    db: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    question: str,
    article_id: str | None = None,
    conversation_id: str | None = None,
    recent_highlights: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
    user=None,
) -> AsyncIterator[dict]:
    """流式聊天：逐 token yield，最后 yield done 事件。

    Yields:
        {"type": "token", "text": "..."}
        {"type": "done", "data": {...}}
    """

    t0 = perf_counter()

    # ========== phase 1 初始化 ==========
    t_model = perf_counter()
    model = build_user_chat_model(user) if user else None
    logger.debug("chat.init_model", duration_ms=_ms(t_model))
    if model is None:
        yield {"type": "done", "data": _error_done("model_not_configured")}
        return

    settings = get_settings()

    # ========== phase 2 加载会话与上下文 ==========
    t_ctx = perf_counter()
    (
        conversation,
        notebook_title,
        article_title,
        resolved_article_id,
        notebook_article_count,
        notebook_indexed_article_count,
        should_autotitle,
    ) = await _prepare_context(
        db, user_id=user_id, notebook_id=notebook_id,
        question=question, article_id=article_id, conversation_id=conversation_id,
    )
    logger.info("chat.prepare_context", duration_ms=_ms(t_ctx),
                notebook_id=notebook_id, has_article=bool(resolved_article_id),
                article_count=notebook_article_count, indexed_count=notebook_indexed_article_count)

    recent_history_limit = max(int(settings.chat_recent_history_limit), 4)
    t_hist = perf_counter()
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in await repo.list_recent_messages(
            db,
            conversation_id=conversation.id,
            limit=max(recent_history_limit + 2, 12),
        )
    ]
    logger.debug("chat.load_history", duration_ms=_ms(t_hist), turns=len(history))
    history = history[-recent_history_limit:]
    rolling_summary = str(conversation.rolling_summary or "").strip()
    if rolling_summary:
        history = [{
            "role": "system",
            "content": f"[rolling_summary]\n{rolling_summary[: int(settings.chat_history_summary_max_chars)]}",
        }, *history]
    if recent_turns:
        safe_recent_turns = [
            {
                "role": str(turn.get("role") or "user")[:32],
                "content": str(turn.get("content") or "")[:400],
            }
            for turn in recent_turns[-recent_history_limit:]
            if str(turn.get("content") or "").strip()
        ]
        if safe_recent_turns:
            history = safe_recent_turns
    merged_settings = get_merged_user_settings(user) if user else {}
    custom_system_prompt = str(merged_settings.get("customSystemPrompt") or "").strip()
    answer_length_preference = str(merged_settings.get("answerLengthPreference") or "adaptive").strip().lower()
    output_language = str(merged_settings.get("outputLanguage") or "简体中文").strip() or "简体中文"
    title_task = None
    if should_autotitle:
        title_task = asyncio.create_task(
            _generate_conversation_title(
                question=question,
                notebook_title=notebook_title,
                article_title=article_title,
                user=user,
            ),
            name=f"chat-title:{conversation.id}",
        )

    graph = get_chat_graph()
    graph_timeout_seconds = max(settings.chat_graph_deadline_ms / 1000, 1.0)
    deadline_monotonic = perf_counter() + graph_timeout_seconds
    graph_input = {
        "query": question,
        "notebook_id": notebook_id,
        "article_id": resolved_article_id,
        "user_id": user_id,
        "user": user,
        "notebook_title": notebook_title,
        "article_title": article_title,
        "history": history,
        "rolling_summary": rolling_summary,
        "custom_system_prompt": custom_system_prompt,
        "answer_length_preference": answer_length_preference,
        "output_language": output_language,
        "recent_highlights": _normalize_recent_highlights(recent_highlights or []),
        "notebook_article_count": notebook_article_count,
        "notebook_indexed_article_count": notebook_indexed_article_count,
        "deadline_monotonic": deadline_monotonic,
        "db": db,
        "route": "general",
        "retrieval_scope": "none",
        "output_mode": "concise",
        "tools_needed": [],
        "router_need_web_search": False,
        "router_web_search_reason": "not_needed",
        "retrieval_plan": None,
        "local_evidence": [],
        "need_web_search": False,
        "web_search_reason": "not_needed",
        "web_evidence": [],
        "answer_text": "",
        "raw_citations": [],
        "verified_citations": [],
        "trace_log": {},
    }
    t_graph = perf_counter()
    logger.info("chat.graph_start", conversation_id=conversation.id,
                graph_timeout_ms=round(graph_timeout_seconds * 1000, 2))
    try:
        state = await asyncio.wait_for(graph.ainvoke(graph_input), timeout=graph_timeout_seconds)
        logger.info("chat.graph_done", duration_ms=_ms(t_graph), conversation_id=conversation.id)
    except asyncio.TimeoutError:
        logger.warning("chat.graph_timeout", duration_ms=_ms(t_graph),
                       conversation_id=conversation.id, timeout_ms=settings.chat_graph_deadline_ms)
        state = _fallback_chat_state(
            reason="graph_timeout",
            answer="抱歉，本轮回答超时了。你可以缩小问题范围，或稍后再试。",
        )
    except Exception as exc:
        logger.exception("chat.graph_failed", duration_ms=_ms(t_graph),
                         error=str(exc)[:200], conversation_id=conversation.id)
        state = _fallback_chat_state(
            reason="graph_failed",
            answer="抱歉，当前回答链路出现异常，请稍后重试。",
        )

    route = state.get("route", "general")

    full_answer = str(state.get("answer_text") or "").strip()
    if not full_answer:
        full_answer = "抱歉，我暂时没能生成有效回答，请重试一次。"
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
    t_persist = perf_counter()
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
    conversation_title = _sanitize_conversation_title(conversation.title)
    if should_autotitle:
        conversation_title = await _resolve_conversation_title(
            title_task=title_task,
            fallback_question=question,
        )
        if conversation_title and conversation_title != (conversation.title or ""):
            await repo.update_conversation_title(
                db,
                conversation_id=conversation.id,
                title=conversation_title,
            )
    t_summary = perf_counter()
    await _maybe_refresh_rolling_summary(
        db,
        conversation_id=conversation.id,
        max_chars=int(settings.chat_history_summary_max_chars),
        trigger_messages=int(settings.chat_history_summary_trigger_messages),
        keep_recent=recent_history_limit,
    )
    logger.debug("chat.rolling_summary", duration_ms=_ms(t_summary))
    t_commit = perf_counter()
    await db.commit()
    logger.info("chat.persist", duration_ms=_ms(t_persist),
                commit_ms=_ms(t_commit), conversation_id=conversation.id)

    # ========== phase 7 指标 ==========
    observe_chat_e2e(duration_ms=elapsed_ms)
    observe_chat_route_mix(route=route)
    observe_chat_retrieval(route=route, evidence_count=len(local_evidence), recommendation_count=0)
    logger.info(
        "chat.completed",
        route=route,
        conversation_id=conversation.id,
        elapsed_ms=elapsed_ms,
        graph_ms=_ms(t_graph),
        context_ms=_ms(t_ctx),
        persist_ms=_ms(t_persist),
        web_searched=need_web_search,
        citations=len(verified_citations),
        answer_len=len(full_answer),
    )

    yield {
        "type": "done",
        "data": {
            "route": route,
            "routeBadge": _ROUTE_BADGES.get(route, "General answer"),
            "answer": full_answer,
            "evidence": verified_citations,
            "conversationId": conversation.id,
            "conversationTitle": conversation_title or conversation.title or _fallback_conversation_title(question),
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
    recent_highlights: list[dict] | None = None,
    recent_turns: list[dict] | None = None,
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
        recent_highlights=recent_highlights,
        recent_turns=recent_turns,
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
            title=None,
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

    total_articles_result = await db.execute(
        select(func.count(Article.id)).where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
        )
    )
    notebook_article_count = int(total_articles_result.scalar() or 0)
    indexed_articles_result = await db.execute(
        select(func.count(Article.id)).where(
            Article.user_id == user_id,
            Article.notebook_id == notebook_id,
            Article.index_status == "completed",
        )
    )
    notebook_indexed_article_count = int(indexed_articles_result.scalar() or 0)

    await repo.append_message(
        db, conversation_id=conversation.id, role="user",
        content=question, article_id=resolved_article_id,
    )

    notebook_title = notebook.title or ""
    should_autotitle = not _sanitize_conversation_title(conversation.title)

    return (
        conversation,
        notebook_title,
        article_title,
        resolved_article_id,
        notebook_article_count,
        notebook_indexed_article_count,
        should_autotitle,
    )


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


def _normalize_recent_highlights(items: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for item in items[:8]:
        text = str(item.get("text") or item.get("selectedText") or "").strip()
        if not text:
            continue
        normalized.append({
            "id": str(item.get("id") or ""),
            "article_id": str(item.get("articleId") or item.get("article_id") or ""),
            "text": text[:1200],
            "comment": str(item.get("comment") or "").strip()[:600],
            "color": str(item.get("color") or "").strip().lower()[:24],
        })
    return normalized


def _fallback_chat_state(*, reason: str, answer: str) -> dict:
    return {
        "route": "general",
        "answer_text": answer,
        "verified_citations": [],
        "need_web_search": False,
        "local_evidence": [],
        "trace_log": {
            "route": "general",
            "fallback_reason": reason,
            "citation_count": 0,
            "invalid_citation_count": 0,
            "web_searched": False,
        },
    }


async def _maybe_refresh_rolling_summary(
    db: AsyncSession,
    *,
    conversation_id: str,
    max_chars: int,
    trigger_messages: int,
    keep_recent: int,
) -> None:
    messages = await repo.list_recent_messages(
        db,
        conversation_id=conversation_id,
        limit=max(trigger_messages + keep_recent + 4, 40),
    )
    if len(messages) <= trigger_messages:
        return
    archived = messages[:-keep_recent]
    if not archived:
        return
    summary = _build_rolling_summary(archived, max_chars=max_chars)
    if not summary:
        return
    await repo.update_conversation_rolling_summary(
        db,
        conversation_id=conversation_id,
        rolling_summary=summary,
    )


def _build_rolling_summary(messages, *, max_chars: int) -> str:
    bullet_lines: list[str] = []
    for message in messages[-18:]:
        role = "用户" if message.role == "user" else "助手"
        text = (message.content or "").strip()
        if not text:
            continue
        snippet = re.sub(r"\s+", " ", text)[:120]
        bullet_lines.append(f"- {role}：{snippet}")
    if not bullet_lines:
        return ""
    content = "历史对话要点（早期轮次）\n" + "\n".join(bullet_lines)
    return content[:max(max_chars, 200)]


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _flatten_llm_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return str(content or "")


def _sanitize_conversation_title(value: str | None) -> str:
    normalized = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    normalized = normalized.strip("'\"`“”‘’[](){}<>")
    return normalized[:_AUTO_CONVERSATION_TITLE_MAX_LEN]


def _heuristic_conversation_title(question: str) -> str:
    normalized = _sanitize_conversation_title(question)
    if not normalized:
        return ""
    cleaned = normalized
    cleaned = re.sub(r"^(请问|请你|请帮我|帮我|麻烦你|麻烦|可以|能不能|我想知道|想了解)+", "", cleaned)
    cleaned = re.sub(r"(请只回答|只回答|并给出引用|并附上引用|并说明核心原因|并说明原因|并给出证据).*$", "", cleaned)
    cleaned = cleaned.strip("，。！？?!.；;：:、 ")

    ascii_terms: list[str] = []
    for term in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", cleaned):
        if term not in ascii_terms:
            ascii_terms.append(term)

    if ("比较" in cleaned or "对比" in cleaned or "差异" in cleaned) and len(ascii_terms) >= 2:
        return _sanitize_conversation_title(f"{ascii_terms[0]} vs {ascii_terms[1]}")
    if ("为什么" in cleaned or "为何" in cleaned or "原因" in cleaned) and ascii_terms:
        suffix = "推荐原因" if ("推荐" in cleaned or "建议" in cleaned) else "原因"
        return _sanitize_conversation_title(f"{ascii_terms[0]} {suffix}")
    if "总结" in cleaned and ascii_terms:
        return _sanitize_conversation_title(f"{ascii_terms[0]} 总结")
    if "差异" in cleaned and ascii_terms:
        return _sanitize_conversation_title(f"{ascii_terms[0]} 差异")

    compact = re.sub(r"^(总结|分析|解释|说明|比较|对比)+", "", cleaned).strip()
    compact = compact[:18].strip()
    return _sanitize_conversation_title(compact or cleaned[:18])


def _fallback_conversation_title(question: str) -> str:
    heuristic = _heuristic_conversation_title(question)
    if heuristic:
        return heuristic
    normalized = _sanitize_conversation_title(question)
    return normalized[:24] or "新对话"


async def _generate_conversation_title(
    *,
    question: str,
    notebook_title: str,
    article_title: str,
    user=None,
) -> str | None:
    model = build_lite_llm() or build_user_chat_model(user)
    if model is None:
        return None
    notebook_text = _sanitize_conversation_title(notebook_title) or "未命名笔记本"
    article_text = _sanitize_conversation_title(article_title) or "当前文章未知"
    user_prompt = (
        "请为一次研究助手对话生成一个简短中文标题。\n"
        "要求：不超过18个中文字符；直接概括用户意图；不要用引号、句号、前缀或 emoji。\n"
        f"笔记本：{notebook_text}\n"
        f"当前文章：{article_text}\n"
        f"用户问题：{question[:500]}\n"
        "仅输出标题。"
    )
    try:
        response = await asyncio.wait_for(
            model.ainvoke([
                SystemMessage(content="你是对话标题生成器。"),
                HumanMessage(content=user_prompt),
            ]),
            timeout=_AUTO_CONVERSATION_TITLE_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    generated = _sanitize_conversation_title(_flatten_llm_content(getattr(response, "content", "")))
    return generated or None


async def _resolve_conversation_title(
    *,
    title_task: asyncio.Task | None,
    fallback_question: str,
) -> str:
    fallback = _fallback_conversation_title(fallback_question)
    if title_task is None:
        return fallback
    try:
        generated = await asyncio.wait_for(asyncio.shield(title_task), timeout=_AUTO_CONVERSATION_TITLE_AWAIT_SECONDS)
    except Exception:
        if not title_task.done():
            title_task.cancel()
        return fallback
    return _sanitize_conversation_title(generated) or fallback


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
