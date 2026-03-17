"""LangGraph ReAct chat agent.

Uses ``create_react_agent`` to build a proper multi-step agent that can:
  1. Decide if it needs to search (and what to search)
  2. Execute retrieval tools
  3. Inspect results, decide if more searching is needed
  4. Generate final answer with evidence

This replaces manual bind_tools + one-shot invocation.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.prebuilt import create_react_agent

from app.modules.agent.chat.prompts import SYSTEM_PROMPT
from app.modules.agent.tools.chat_retrieval import (
    search_article_chunks,
    search_notebook_articles,
    set_tool_context,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

TOOLS = [search_article_chunks, search_notebook_articles]


async def run_chat_agent(
    model,
    db: AsyncSession,
    *,
    question: str,
    article_id: str | None,
    notebook_id: str,
    user_id: str,
    notebook_title: str = "",
    article_title: str = "",
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Run the ReAct agent and return structured result."""

    set_tool_context(
        db,
        article_id=article_id,
        notebook_id=notebook_id,
        user_id=user_id,
    )

    system = SystemMessage(content=SYSTEM_PROMPT.format(
        notebook_title=notebook_title or "Untitled",
        article_title=article_title or "No article selected",
    ))

    agent = create_react_agent(model, TOOLS, prompt=SystemMessage(content=system_prompt))

    input_messages: list = []
    if history:
        for turn in history[-6:]:
            if turn.get("role") == "user":
                input_messages.append(HumanMessage(content=turn["content"]))
            elif turn.get("role") == "assistant":
                from langchain_core.messages import AIMessage
                input_messages.append(AIMessage(content=turn["content"]))
    input_messages.append(HumanMessage(content=question))

    result = await agent.ainvoke({"messages": input_messages})

    all_messages = result.get("messages", [])
    answer = ""
    tool_calls_made: list[str] = []
    evidence: list[dict] = []

    for msg in all_messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_made.append(tc.get("name", ""))
        if hasattr(msg, "content") and msg.type == "ai" and not getattr(msg, "tool_calls", None):
            answer = msg.content or ""

    if not answer and all_messages:
        last = all_messages[-1]
        answer = getattr(last, "content", "") or ""

    route = _infer_route(tool_calls_made)

    return {
        "answer": answer,
        "route": route,
        "evidence": evidence,
        "tool_calls_made": tool_calls_made,
    }


def _infer_route(tool_calls: list[str]) -> str:
    if "search_article_chunks" in tool_calls:
        return "article"
    if "search_notebook_articles" in tool_calls:
        return "notebook"
    return "general"
