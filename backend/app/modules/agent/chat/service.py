"""Chat service – manages conversation state and runs the LangGraph agent.

Architecture: load conversation → run agent (LLM + tools) → persist messages.
"""

from __future__ import annotations

import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.ai.chat_models import build_user_chat_model
from app.modules.agent.chat import repo
from app.modules.agent.chat.graph import run_chat_agent
from app.modules.notebooks import repo as notebooks_repo

logger = structlog.get_logger(__name__)

_ROUTE_BADGES = {
    "article": "From this article",
    "notebook": "From your notebooks",
    "general": "General answer",
}


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
    """Process a chat message and return structured result.

    Returns:
        {
            "answer_text": str,
            "route": str,
            "route_badge": str,
            "evidence": [...],
            "conversation_id": str,
            "message_id": str,
        }
    """

    model = build_user_chat_model(user) if user else None
    if model is None:
        return {
            "answer_text": "",
            "route": "general",
            "route_badge": "General answer",
            "evidence": [],
            "error": "model_not_configured",
        }

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
        db,
        conversation_id=conversation.id,
        role="user",
        content=question,
        article_id=article_id,
    )

    history = [
        {"role": msg.role, "content": msg.content}
        for msg in await repo.list_recent_messages(db, conversation_id=conversation.id, limit=6)
    ]

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

    try:
        result = await run_chat_agent(
            model,
            db,
            question=question,
            article_id=article_id,
            notebook_id=notebook_id,
            user_id=user_id,
            notebook_title=notebook_title,
            article_title=article_title,
            history=history,
        )
    except Exception as exc:
        logger.exception("chat.agent_failed", error=str(exc))
        result = {
            "answer": f"抱歉，处理您的问题时出错了：{str(exc)[:200]}",
            "route": "general",
            "evidence": [],
            "tool_calls_made": [],
        }

    route = result.get("route", "general")
    answer_text = result.get("answer", "")

    assistant_msg = await repo.append_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=answer_text,
        article_id=article_id,
        route=route,
        retrieval_snapshot_json=json.dumps(
            {"evidence": result.get("evidence", []), "tool_calls": result.get("tool_calls_made", [])},
            ensure_ascii=False,
            default=str,
        ),
    )

    await db.commit()

    return {
        "answer_text": answer_text,
        "route": route,
        "route_badge": _ROUTE_BADGES.get(route, "General answer"),
        "evidence": result.get("evidence", []),
        "conversation_id": conversation.id,
        "message_id": assistant_msg.id,
    }
