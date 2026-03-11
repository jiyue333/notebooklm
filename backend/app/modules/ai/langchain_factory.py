from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from app.modules.ai.prompts.chat_route_prompt import (
    CHAT_ROUTE_SYSTEM_PROMPT,
    CHAT_ROUTE_USER_PROMPT,
)
from app.modules.ai.prompts.chat_prompt import (
    CHAT_ROLLUP_SYSTEM_PROMPT,
    CHAT_ROLLUP_USER_PROMPT,
    CHAT_SYSTEM_PROMPT,
    CHAT_USER_PROMPT,
)
from app.modules.ai.prompts.summary_prompt import SUMMARY_SYSTEM_PROMPT, SUMMARY_USER_PROMPT


def build_chat_router_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_ROUTE_SYSTEM_PROMPT),
            ("human", CHAT_ROUTE_USER_PROMPT),
        ]
    )


def build_summary_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_SYSTEM_PROMPT),
            ("human", SUMMARY_USER_PROMPT),
        ]
    )


def build_chat_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_SYSTEM_PROMPT),
            MessagesPlaceholder("history_messages"),
            ("human", CHAT_USER_PROMPT),
        ]
    )


def build_chat_rollup_prompt():
    return ChatPromptTemplate.from_messages(
        [
            ("system", CHAT_ROLLUP_SYSTEM_PROMPT),
            ("human", CHAT_ROLLUP_USER_PROMPT),
        ]
    )
