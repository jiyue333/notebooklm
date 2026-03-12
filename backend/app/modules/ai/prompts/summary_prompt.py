from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

SUMMARY_PROMPT_VERSION = "summary.v1"

SUMMARY_SYSTEM_PROMPT = """
你是一个阅读助手。请严格基于提供的文章内容生成摘要，不要编造未出现的信息。
输出语言必须是 {output_language}。
摘要要适合直接展示给最终用户，结构清晰、信息密度高，优先提炼主题、关键观点和可行动结论。
""".strip()

SUMMARY_USER_PROMPT = """
请为下面这篇文章生成摘要。

标题：{title}

正文：
{content}
""".strip()


def build_summary_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", SUMMARY_SYSTEM_PROMPT),
            ("human", SUMMARY_USER_PROMPT),
        ]
    )
