"""Node 5: Answer Generator — 按场景拼接上下文并生成答案。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.infra.ai.chat_models import build_user_chat_model
from app.infra.telemetry.metrics import (
    observe_chat_answer_length,
    observe_chat_error,
    observe_chat_stage,
    observe_chat_token_cost,
)
from app.modules.agent.chat.prompts import (
    ANSWER_SYSTEMS,
    ANSWER_USER_GENERAL,
    ANSWER_USER_GROUNDED,
)
from app.modules.agent.chat.state import ChatGraphState

logger = structlog.get_logger(__name__)


def _extract_token_cost(resp) -> int:
    meta = getattr(resp, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return int(usage.get("total_tokens", 0))


async def answer_generator_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    user = state.get("user")
    model = build_user_chat_model(user) if user else None
    if model is None:
        observe_chat_stage(stage="answer_generator", route=route, status="skip", duration_ms=_ms(t0))
        return {"answer_text": "模型未配置，无法生成回答。", "raw_citations": []}

    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])
    history = state.get("history", [])

    system = ANSWER_SYSTEMS.get(route, ANSWER_SYSTEMS["general"])
    history_text = _format_history(history)

    # ========== 按 route 构建 user message ==========
    if route == "general":
        evidence_parts: list[str] = []
        local_text = _format_local_evidence(local_evidence)
        web_text = _format_web_evidence(web_evidence)
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
            local_evidence_text=_format_local_evidence(local_evidence) or "(无本地证据)",
            web_evidence_text=_format_web_evidence(web_evidence) or "(无网络证据)",
            history_text=history_text or "(无历史对话)",
            query=state["query"],
        )

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_msg),
    ]

    try:
        resp = await model.ainvoke(messages)
        answer = (resp.content or "").strip()
        tokens = _extract_token_cost(resp)
        if tokens:
            observe_chat_token_cost(route=route, tokens=tokens)
    except Exception as exc:
        logger.exception("chat.answer_gen_failed", error=str(exc)[:200])
        observe_chat_error(node="answer_generator")
        observe_chat_stage(stage="answer_generator", route=route, status="error", duration_ms=_ms(t0))
        answer = f"抱歉，生成回答时出错了：{str(exc)[:100]}"

    citations = _extract_citations(answer)

    observe_chat_answer_length(route=route, length=len(answer))
    observe_chat_stage(stage="answer_generator", route=route, status="ok", duration_ms=_ms(t0))

    return {
        "answer_text": answer,
        "raw_citations": citations,
    }


def _format_local_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    lines: list[str] = []
    for i, e in enumerate(evidence, 1):
        heading = e.get("heading_title") or e.get("section_path") or ""
        title = e.get("article_title", "")
        prefix = f"{title} > {heading}" if heading else title
        text = e.get("raw_text", "")[:400]
        lines.append(f"[{i}] {prefix}: {text}")
    return "\n\n".join(lines)


def _format_web_evidence(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    lines: list[str] = []
    for i, e in enumerate(evidence, 1):
        title = e.get("title", "")
        url = e.get("url", "")
        snippet = e.get("snippet", "")[:300]
        lines.append(f"[W{i}] {title} ({url}): {snippet}")
    return "\n\n".join(lines)


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")[:300]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _extract_citations(text: str) -> list[dict]:
    """从回答文本中提取 [N] 和 [WN] 引用标记。"""
    citations: list[dict] = []
    for m in re.finditer(r"\[(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "local"})
    for m in re.finditer(r"\[W(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "web"})
    return citations


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
