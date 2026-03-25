"""Summary graph 节点函数。"""

from __future__ import annotations

import json
import re
from time import perf_counter
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import get_settings
from app.infra.ai.chat_models import build_user_chat_model
from app.infra.ai.lite_models import build_lite_llm
from app.infra.telemetry.metrics import (
    observe_summary_compression_ratio,
    observe_summary_judge_reject,
    observe_summary_model_tier,
    observe_summary_stage,
    observe_summary_strategy,
    observe_summary_token_cost,
    observe_summary_validation_result,
)
from app.modules.agent.summary.compress import compress_content
from app.modules.agent.summary.prompts import (
    MAP_PROMPT,
    REDUCE_PROMPT,
    SYSTEM_PROMPT,
    USER_PROMPTS,
    VALIDATE_PROMPT,
)
from app.modules.agent.summary.state import SummaryGraphState

logger = structlog.get_logger(__name__)


def _extract_token_cost(resp) -> int:
    meta = getattr(resp, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return int(usage.get("total_tokens", 0))


# ========== Node 1: analyze_content ==========

def analyze_content(state: SummaryGraphState) -> dict[str, Any]:
    """分析文章类型、统计内容指标、选择模型档位。"""
    t0 = perf_counter()
    text = state["clean_markdown"]

    total_chars = len(text)
    code_chars = sum(
        len(m.group(0)) for m in re.finditer(r"```\w*\n.*?```", text, re.DOTALL)
    )
    code_ratio = code_chars / max(total_chars, 1)
    table_count = len(re.findall(r"^\|.*\|$", text, re.MULTILINE)) // 3
    image_count = len(re.findall(r"!\[", text))
    token_count = max(1, total_chars // 4)

    text_lower = text[:3000].lower()

    if code_ratio > 0.30:
        article_type = "code_heavy"
    elif any(kw in text_lower for kw in ("abstract", "methodology", "references", "conclusion", "摘要", "方法论", "参考文献")):
        article_type = "research"
    elif any(kw in text_lower for kw in ("step ", "tutorial", "how to", "教程", "步骤")):
        article_type = "tutorial"
    elif any(kw in text_lower for kw in ("reported", "announced", "according to", "据报道", "消息称")):
        article_type = "news"
    else:
        article_type = "general"

    model_tier = "lite" if token_count < 4000 else "standard"

    observe_summary_stage(stage="analyze", status="ok", duration_ms=_ms(t0))
    observe_summary_model_tier(tier=model_tier)
    observe_summary_strategy(
        strategy="map_reduce" if token_count > get_settings().summary_map_reduce_threshold_tokens else "direct",
    )

    return {
        "article_type": article_type,
        "content_stats": {
            "token_count": token_count,
            "code_ratio": round(code_ratio, 3),
            "table_count": table_count,
            "image_count": image_count,
        },
        "model_tier": model_tier,
    }


# ========== Node 2: compress_content_node ==========

def compress_content_node(state: SummaryGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    settings = get_settings()
    original = state["clean_markdown"]
    compressed = compress_content(
        original,
        compress_code=settings.summary_compress_code_blocks,
    )

    observe_summary_stage(stage="compress", status="ok", duration_ms=_ms(t0))
    if original:
        observe_summary_compression_ratio(ratio=len(compressed) / max(len(original), 1))

    return {"compressed_content": compressed}


# ========== Node 3: direct_summarize ==========

async def direct_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """直接调用 LLM 生成摘要。"""
    t0 = perf_counter()
    model = _resolve_model(state)
    if model is None:
        observe_summary_stage(stage="direct_summarize", status="skip", duration_ms=_ms(t0))
        return {"summary_text": ""}

    article_type = state.get("article_type", "general")
    user_template = USER_PROMPTS.get(article_type, USER_PROMPTS["general"])

    system = SYSTEM_PROMPT
    language = state.get("language", "auto")
    if language == "zh":
        system += "\n\nIMPORTANT: Write the summary in 简体中文."

    content = state.get("compressed_content") or state["clean_markdown"]
    max_chars = 48000
    content = content[:max_chars]

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_template.format(
            title=state.get("title", ""),
            content=content,
        )),
    ]

    try:
        resp = await model.ainvoke(messages)
        tokens = _extract_token_cost(resp)
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="direct_summarize", status="ok", duration_ms=_ms(t0))
        return {"summary_text": (resp.content or "").strip()}
    except Exception as exc:
        logger.exception("summary.direct_failed", error=str(exc)[:200])
        observe_summary_stage(stage="direct_summarize", status="error", duration_ms=_ms(t0))
        return {"summary_text": ""}


# ========== Node 4: map_split ==========

def map_split(state: SummaryGraphState) -> dict[str, Any]:
    """将压缩后内容按 ~4k tokens 分块，供 map 阶段并行摘要。"""
    t0 = perf_counter()
    content = state.get("compressed_content") or state["clean_markdown"]
    chunk_char_size = 16000  # ~4k tokens
    chunks: list[str] = []
    start = 0
    while start < len(content):
        end = start + chunk_char_size
        chunk = content[start:end]
        if end < len(content):
            break_pos = chunk.rfind("\n\n")
            if break_pos > chunk_char_size // 2:
                end = start + break_pos
                chunk = content[start:end]
        stripped = chunk.strip()
        if stripped:
            chunks.append(stripped)
        start = end

    observe_summary_stage(stage="map_split", status="ok", duration_ms=_ms(t0))
    return {"map_chunks": chunks}


# ========== Node 5: map_summarize ==========

async def map_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """对单个 map chunk 生成摘要。"""
    t0 = perf_counter()
    model = build_lite_llm()
    if model is None:
        model = _resolve_model(state)
    if model is None:
        observe_summary_stage(stage="map_summarize", status="skip", duration_ms=_ms(t0))
        return {"chunk_summaries": [""]}

    chunk = state.get("subject", "")
    if not chunk:
        chunks = state.get("map_chunks", [])
        chunk = chunks[0] if chunks else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=MAP_PROMPT.format(
            title=state.get("title", ""),
            chunk=chunk[:16000],
        )),
    ]

    try:
        resp = await model.ainvoke(messages)
        tokens = _extract_token_cost(resp)
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="map_summarize", status="ok", duration_ms=_ms(t0))
        return {"chunk_summaries": [(resp.content or "").strip()]}
    except Exception as exc:
        logger.warning("summary.map_failed", error=str(exc)[:200])
        observe_summary_stage(stage="map_summarize", status="error", duration_ms=_ms(t0))
        return {"chunk_summaries": [""]}


# ========== Node 6: reduce_summarize ==========

async def reduce_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """合并 map 阶段的中间摘要为最终摘要。"""
    t0 = perf_counter()
    model = _resolve_model(state)
    if model is None:
        observe_summary_stage(stage="reduce_summarize", status="skip", duration_ms=_ms(t0))
        return {"summary_text": "\n\n".join(state.get("chunk_summaries", []))}

    summaries_text = "\n\n---\n\n".join(
        f"[Section {i+1}]\n{s}" for i, s in enumerate(state.get("chunk_summaries", [])) if s
    )

    system = SYSTEM_PROMPT
    if state.get("language") == "zh":
        system += "\n\nIMPORTANT: Write the summary in 简体中文."

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=REDUCE_PROMPT.format(
            title=state.get("title", ""),
            summaries=summaries_text[:32000],
        )),
    ]

    try:
        resp = await model.ainvoke(messages)
        tokens = _extract_token_cost(resp)
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="reduce_summarize", status="ok", duration_ms=_ms(t0))
        return {"summary_text": (resp.content or "").strip()}
    except Exception as exc:
        logger.warning("summary.reduce_failed", error=str(exc)[:200])
        observe_summary_stage(stage="reduce_summarize", status="error", duration_ms=_ms(t0))
        return {"summary_text": "\n\n".join(state.get("chunk_summaries", []))}


# ========== Node 7: validate_summary ==========

async def validate_summary(state: SummaryGraphState) -> dict[str, Any]:
    """用 lite_model 校验摘要质量。"""
    t0 = perf_counter()
    retry_count = state.get("retry_count", 0) + 1

    summary = state.get("summary_text", "")
    if not summary:
        observe_summary_stage(stage="validate", status="ok", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=False)
        return {
            "validation_passed": False,
            "validation_issues": ["empty_summary"],
            "retry_count": retry_count,
        }

    model = build_lite_llm()
    if model is None:
        observe_summary_stage(stage="validate", status="skip", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=True)
        return {"validation_passed": True, "validation_issues": [], "retry_count": retry_count}

    messages = [
        SystemMessage(content="You are a summary quality evaluator. Return ONLY valid JSON."),
        HumanMessage(content=VALIDATE_PROMPT.format(
            title=state.get("title", ""),
            summary=summary,
        )),
    ]

    try:
        resp = await model.ainvoke(messages)
        raw = (resp.content or "").strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group(0))
            passed = bool(result.get("passed", True))
            issues = result.get("issues", [])
            observe_summary_stage(stage="validate", status="ok", duration_ms=_ms(t0))
            observe_summary_validation_result(passed=passed)
            if not passed:
                for issue in issues[:3]:
                    observe_summary_judge_reject(reason=str(issue)[:32])
            return {"validation_passed": passed, "validation_issues": issues, "retry_count": retry_count}
    except Exception as exc:
        logger.debug("summary.validate_parse_failed", error=str(exc)[:120])

    observe_summary_stage(stage="validate", status="ok", duration_ms=_ms(t0))
    observe_summary_validation_result(passed=True)
    return {"validation_passed": True, "validation_issues": [], "retry_count": retry_count}


# ── 工具函数 ──────────────────────────────────────────────────────

def _resolve_model(state: SummaryGraphState):
    tier = state.get("model_tier", "standard")
    if tier == "lite":
        m = build_lite_llm()
        if m is not None:
            return m
    user = state.get("user")
    return build_user_chat_model(user) if user else None


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
