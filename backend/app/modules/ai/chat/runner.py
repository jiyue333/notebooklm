from __future__ import annotations

from time import perf_counter

from app.api.errors import AppError
from app.infra.telemetry.llm import extract_llm_text_and_usage
from app.infra.telemetry.metrics import observe_llm_call


async def run_chat_completion(prepared) -> str:
    started_at = perf_counter()
    try:
        result = await prepared.model.ainvoke(
            prepared.messages,
            config={"run_name": "chat_model", "metadata": prepared.trace_metadata},
        )
    except Exception:
        observe_llm_call(
            operation="chat",
            provider=prepared.model_settings["modelProvider"],
            model=prepared.model_settings["modelName"],
            status="error",
            duration_ms=round((perf_counter() - started_at) * 1000, 2),
        )
        raise
    answer, usage = extract_llm_text_and_usage(result)
    observe_llm_call(
        operation="chat",
        provider=prepared.model_settings["modelProvider"],
        model=prepared.model_settings["modelName"],
        status="success",
        duration_ms=round((perf_counter() - started_at) * 1000, 2),
        usage=usage,
    )
    if not answer:
        raise AppError(502, "对话生成失败", code="chat_generation_failed")
    return answer
