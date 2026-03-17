"""聊天编排：基于 LangChain 当前 agent 运行时。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import structlog
from langchain.agents import create_agent
from langchain.agents.middleware import wrap_model_call
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.modules.agent.chat.prompts import SYSTEM_PROMPT
from app.modules.agent.tools.chat_retrieval import (
    ChatToolContext,
    search_article_chunks,
    search_notebook_articles,
)
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

TOOLS = [search_article_chunks, search_notebook_articles]
_ARTICLE_HINTS = ("这篇", "本文", "文中", "文章里", "当前文章", "current article", "this article")
_NOTEBOOK_HINTS = ("notebook", "所有文章", "相关文章", "研究", "综述", "总结", "对比", "compare")


class ChatAgentOutput(BaseModel):
    """聊天 agent 的结构化输出。"""

    answer: str = Field(description="给用户的最终回答")
    route: Literal["article", "notebook", "general"] = Field(description="回答来源路由")
    evidence: list[dict[str, Any]] = Field(default_factory=list, description="引用证据")
    tool_calls_made: list[str] = Field(default_factory=list, description="执行过的工具名")


def _extract_last_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", "") == "human":
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _select_chat_tools(*, question: str, context: ChatToolContext) -> list:
    if not context.article_id:
        return [search_notebook_articles]

    lowered = question.lower()
    if any(hint in question for hint in _ARTICLE_HINTS):
        return [search_article_chunks]
    if any(hint in lowered or hint in question for hint in _NOTEBOOK_HINTS):
        return [search_notebook_articles]
    return TOOLS


@wrap_model_call
def _chat_tool_selector(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    context = request.runtime.context
    if not isinstance(context, ChatToolContext):
        return handler(request)

    state = request.state
    messages = state.get("messages", []) if hasattr(state, "get") else getattr(state, "messages", [])
    selected_tools = _select_chat_tools(
        question=_extract_last_user_text(messages),
        context=context,
    )
    return handler(request.override(tools=selected_tools))


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
    """执行聊天 agent，并返回结构化结果。"""

    # ========== phase 1 构造上下文 ==========
    system = SystemMessage(content=SYSTEM_PROMPT.format(
        notebook_title=notebook_title or "Untitled",
        article_title=article_title or "No article selected",
    ))

    # ========== phase 2 构造 agent ==========
    agent = create_agent(
        model=model,
        tools=TOOLS,
        system_prompt=system,
        middleware=[_chat_tool_selector],
        response_format=ChatAgentOutput,
        context_schema=ChatToolContext,
        name="notebook_chat_agent",
    )

    # ========== phase 3 组装消息 ==========
    # ====== step 1 回放最近历史 ======
    input_messages: list = []
    if history:
        for turn in history[-6:]:
            if turn.get("role") == "user":
                input_messages.append(HumanMessage(content=turn["content"]))
            elif turn.get("role") == "assistant":
                from langchain_core.messages import AIMessage
                input_messages.append(AIMessage(content=turn["content"]))
    input_messages.append(HumanMessage(content=question))

    # ====== step 2 调用 agent ======
    result = await agent.ainvoke(
        {"messages": input_messages},
        context=ChatToolContext(
            db=db,
            article_id=article_id,
            notebook_id=notebook_id,
            user_id=user_id,
        ),
    )

    # ========== phase 4 解析结果 ==========
    # 优先使用结构化输出；只有在模型未返回时才退回到消息扫描。
    structured = result.get("structured_response")
    if isinstance(structured, ChatAgentOutput):
        return structured.model_dump()
    if isinstance(structured, dict):
        return ChatAgentOutput(**structured).model_dump()

    all_messages = result.get("messages", [])
    answer = ""
    tool_calls_made: list[str] = []

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
        "evidence": [],
        "tool_calls_made": tool_calls_made,
    }


def _infer_route(tool_calls: list[str]) -> str:
    if "search_article_chunks" in tool_calls:
        return "article"
    if "search_notebook_articles" in tool_calls:
        return "notebook"
    return "general"
