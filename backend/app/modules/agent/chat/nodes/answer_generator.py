"""Node 5: Answer Generator — 按场景拼接上下文并生成答案。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
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
_PROMPT_INJECTION_PATTERN = re.compile(
    r"(ignore\s+previous|system\s+prompt|developer\s+message|bypass|越狱|忽略以上|请无视|sudo|rm\s+-rf)",
    re.IGNORECASE,
)
_SECRET_PATTERN = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|api[_-]?key\s*[:=]\s*[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16})",
    re.IGNORECASE,
)

_LENGTH_PREFERENCE_HINTS = {
    "concise": "回答保持简洁，优先 3-5 条要点，避免冗长铺陈。",
    "detailed": "回答尽量详细，给出充分解释、步骤或上下文，必要时分点展开。",
}


def _extract_token_cost(resp) -> int:
    meta = getattr(resp, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return int(usage.get("total_tokens", 0))


async def answer_generator_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    route = state.get("route", "general")
    settings = get_settings()
    user = state.get("user")
    model = build_user_chat_model(user) if user else None
    if model is None:
        observe_chat_stage(stage="answer_generator", route=route, status="skip", duration_ms=_ms(t0))
        return {"answer_text": "模型未配置，无法生成回答。", "raw_citations": []}

    local_evidence = state.get("local_evidence", [])
    web_evidence = state.get("web_evidence", [])
    history = state.get("history", [])
    recent_highlights = state.get("recent_highlights", [])

    answer_length_preference = _normalize_answer_length_preference(state.get("answer_length_preference"))
    output_mode = _resolve_output_mode(state.get("output_mode", "concise"), answer_length_preference)
    system = _build_answer_system_prompt(
        base_system=ANSWER_SYSTEMS.get(route, ANSWER_SYSTEMS["general"]),
        custom_system_prompt=str(state.get("custom_system_prompt") or "").strip(),
        answer_length_preference=answer_length_preference,
        output_language=str(state.get("output_language") or "简体中文").strip() or "简体中文",
    )
    history_text = _format_history(history)

    # ========== 按 route 构建 user message ==========
    if route == "general":
        evidence_parts: list[str] = []
        local_text, local_safety = _format_local_evidence(
            local_evidence,
            max_chars=max(int(settings.chat_evidence_context_budget_chars * 0.65), 1200),
        )
        web_text, web_safety = _format_web_evidence(
            web_evidence,
            max_chars=max(int(settings.chat_evidence_context_budget_chars * 0.35), 600),
        )
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
        local_text, local_safety = _format_local_evidence(
            local_evidence,
            max_chars=max(int(settings.chat_evidence_context_budget_chars * 0.7), 1400),
        )
        web_text, web_safety = _format_web_evidence(
            web_evidence,
            max_chars=max(int(settings.chat_evidence_context_budget_chars * 0.3), 700),
        )
        user_msg = ANSWER_USER_GROUNDED.format(
            output_mode=output_mode,
            local_evidence_text=local_text or "(无本地证据)",
            web_evidence_text=web_text or "(无网络证据)",
            history_text=history_text or "(无历史对话)",
            query=state["query"],
        )

    highlights_text = _format_recent_highlights(recent_highlights)
    if highlights_text:
        user_msg = (
            f"{user_msg}\n\n"
            "## 用户近期高亮与批注（可选参考）：\n"
            f"{highlights_text}"
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
    security_flags = {
        "local_injection_filtered": local_safety["injection_filtered"],
        "local_secret_masked": local_safety["secret_masked"],
        "web_injection_filtered": web_safety["injection_filtered"],
        "web_secret_masked": web_safety["secret_masked"],
    }

    observe_chat_answer_length(route=route, length=len(answer))
    observe_chat_stage(stage="answer_generator", route=route, status="ok", duration_ms=_ms(t0))

    return {
        "answer_text": answer,
        "raw_citations": citations,
        "security_flags": security_flags,
    }


def _format_local_evidence(
    evidence: list[dict],
    *,
    max_chars: int,
) -> tuple[str, dict[str, bool]]:
    if not evidence:
        return "", {"injection_filtered": False, "secret_masked": False}
    lines: list[str] = []
    total = 0
    injection_filtered = False
    secret_masked = False
    for i, e in enumerate(evidence, 1):
        heading = e.get("heading_title") or e.get("section_path") or ""
        title = e.get("article_title", "")
        prefix = f"{title} > {heading}" if heading else title
        raw_text = e.get("raw_text", "")[:420]
        safe_text, safe_meta = _sanitize_evidence_text(raw_text)
        injection_filtered = injection_filtered or safe_meta["injection_filtered"]
        secret_masked = secret_masked or safe_meta["secret_masked"]
        line = f"[{i}] {prefix}: {safe_text}"
        if total + len(line) > max_chars:
            break
        total += len(line)
        lines.append(line)
    return "\n\n".join(lines), {"injection_filtered": injection_filtered, "secret_masked": secret_masked}


def _format_web_evidence(
    evidence: list[dict],
    *,
    max_chars: int,
) -> tuple[str, dict[str, bool]]:
    if not evidence:
        return "", {"injection_filtered": False, "secret_masked": False}
    lines: list[str] = []
    total = 0
    injection_filtered = False
    secret_masked = False
    for i, e in enumerate(evidence, 1):
        title = e.get("title", "")
        url = e.get("url", "")
        snippet_raw = e.get("snippet", "")[:320]
        snippet, safe_meta = _sanitize_evidence_text(snippet_raw)
        injection_filtered = injection_filtered or safe_meta["injection_filtered"]
        secret_masked = secret_masked or safe_meta["secret_masked"]
        line = f"[W{i}] {title} ({url}): {snippet}"
        if total + len(line) > max_chars:
            break
        total += len(line)
        lines.append(line)
    return "\n\n".join(lines), {"injection_filtered": injection_filtered, "secret_masked": secret_masked}


def _format_history(history: list[dict]) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for turn in history[-4:]:
        role = turn.get("role", "user")
        content = turn.get("content", "")[:300]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _format_recent_highlights(items: list[dict]) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for idx, item in enumerate(items[:6], 1):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        comment = str(item.get("comment") or "").strip()
        color = str(item.get("color") or "").strip()
        article_id = str(item.get("article_id") or item.get("articleId") or "").strip()
        prefix = f"[H{idx}]"
        meta_parts = [part for part in [color, f"article:{article_id}" if article_id else ""] if part]
        meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
        lines.append(f"{prefix}{meta} {text[:320]}")
        if comment:
            lines.append(f"    批注: {comment[:200]}")
    return "\n".join(lines)


def _extract_citations(text: str) -> list[dict]:
    """从回答文本中提取 [N] 和 [WN] 引用标记。"""
    citations: list[dict] = []
    for m in re.finditer(r"\[(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "local"})
    for m in re.finditer(r"\[W(\d+)\]", text):
        citations.append({"id": int(m.group(1)), "type": "web"})
    return citations


def _sanitize_evidence_text(text: str) -> tuple[str, dict[str, bool]]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return "", {"injection_filtered": False, "secret_masked": False}
    injection_filtered = False
    secret_masked = False
    if _PROMPT_INJECTION_PATTERN.search(normalized):
        normalized = _PROMPT_INJECTION_PATTERN.sub("[filtered_instruction]", normalized)
        injection_filtered = True
    if _SECRET_PATTERN.search(normalized):
        normalized = _SECRET_PATTERN.sub("[masked_secret]", normalized)
        secret_masked = True
    normalized = normalized.replace("<script", "[script]").replace("</script>", "[/script]")
    return normalized[:420], {"injection_filtered": injection_filtered, "secret_masked": secret_masked}


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _normalize_answer_length_preference(raw: Any) -> str:
    value = str(raw or "adaptive").strip().lower()
    if value not in {"concise", "detailed", "adaptive"}:
        return "adaptive"
    return value


def _resolve_output_mode(route_output_mode: Any, answer_length_preference: str) -> str:
    if answer_length_preference == "concise":
        return "concise"
    if answer_length_preference == "detailed":
        return "detailed"
    value = str(route_output_mode or "concise").strip().lower()
    if value not in {"concise", "detailed", "list"}:
        return "concise"
    return value


def _build_answer_system_prompt(
    *,
    base_system: str,
    custom_system_prompt: str,
    answer_length_preference: str,
    output_language: str,
) -> str:
    sections = [base_system.strip()]
    sections.append(f"附加语言偏好：默认使用 {output_language} 回答。")
    preference_hint = _LENGTH_PREFERENCE_HINTS.get(answer_length_preference)
    if preference_hint:
        sections.append(f"附加长度偏好：{preference_hint}")
    if custom_system_prompt:
        sections.append(
            "用户自定义系统要求（在不违反安全与事实约束前提下优先遵循）：\n"
            f"{custom_system_prompt[:1600]}"
        )
    return "\n\n".join(part for part in sections if part)
