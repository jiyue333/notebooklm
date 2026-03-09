from __future__ import annotations

from app.modules.ai.langchain_factory import build_user_chat_model


async def fallback_to_markdown(*, user, title: str, raw_text: str) -> tuple[str | None, str]:
    from langchain_core.messages import HumanMessage, SystemMessage

    model = build_user_chat_model(user)
    if model is None:
        return None, "llm_markdown_fallback"

    messages = [
        SystemMessage(
            content=(
                "You convert noisy extracted document text into clean markdown. "
                "Return markdown only, preserve headings, lists, tables and links when present."
            )
        ),
        HumanMessage(content=f"Title: {title}\n\nRaw text:\n{raw_text}"),
    ]
    result = await model.ainvoke(messages)
    content = getattr(result, "content", None)
    if isinstance(content, list):
        content = "\n".join(str(item) for item in content)
    return (str(content).strip() if content else None), "llm_markdown_fallback"
