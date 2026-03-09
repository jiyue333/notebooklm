from __future__ import annotations

from time import perf_counter

from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_ingest_fallback, observe_llm_call
from app.modules.ai.langchain_factory import build_user_chat_model
from app.modules.ai.langchain_factory import get_user_generation_settings


async def fallback_to_markdown(*, user, title: str, raw_text: str) -> tuple[str | None, str]:
    from langchain_core.messages import HumanMessage, SystemMessage

    model = build_user_chat_model(user)
    if model is None:
        return None, "llm_markdown_fallback"
    settings = get_user_generation_settings(user)
    trace_metadata = {
        "user_id": user.id,
        "provider": settings["modelProvider"],
        "model_name": settings["modelName"],
        "fallback_type": "llm_markdown",
    }
    observe_ingest_fallback(fallback_type="llm_markdown")

    messages = [
        SystemMessage(
            content=(
                "You convert noisy extracted document text into clean markdown. "
                "Return markdown only, preserve headings, lists, tables and links when present."
            )
        ),
        HumanMessage(content=f"Title: {title}\n\nRaw text:\n{raw_text}"),
    ]
    started_at = perf_counter()
    try:
        result = await model.ainvoke(
            messages,
            config={"run_name": "markdown_fallback_model", "metadata": trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="markdown_fallback",
            provider=settings["modelProvider"],
            model=settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    content, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="markdown_fallback",
        provider=settings["modelProvider"],
        model=settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    return (content if content else None), "llm_markdown_fallback"
