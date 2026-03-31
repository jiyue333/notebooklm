"""Summary graph 节点函数。"""

from __future__ import annotations

import asyncio
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
from app.modules.agent.summary import repo
from app.modules.agent.summary.prompts import (
    MAP_PROMPT,
    PROMPT_VERSION,
    REDUCE_PROMPT,
    SYSTEM_PROMPT,
    USER_PROMPTS,
    VALIDATE_PROMPT,
)
from app.modules.agent.summary.state import SummaryGraphState

logger = structlog.get_logger(__name__)

_HEADING_LINE_RE = re.compile(r"^#{1,6}\s+\S+", re.MULTILINE)
_NEWS_HINTS = (
    "breaking", "reported", "announced", "statement", "press release",
    "据报道", "发布会", "通告", "公告", "消息称",
)
_RESEARCH_HINTS = (
    "abstract", "methodology", "references", "conclusion", "dataset", "experiment",
    "摘要", "方法", "参考文献", "实验", "结论",
)
_TUTORIAL_HINTS = (
    "tutorial", "how to", "step", "installation", "prerequisite",
    "教程", "步骤", "安装", "实践", "快速开始",
)
_MAX_VALIDATE_SOURCE_CHARS = 5000
_COMPRESS_VERSION = "v1"


def _extract_token_cost(resp) -> int:
    meta = getattr(resp, "response_metadata", {}) or {}
    usage = meta.get("token_usage") or meta.get("usage") or {}
    return int(usage.get("total_tokens", 0))


def _estimate_token_count(text: str) -> int:
    if not text:
        return 1
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    punctuation = len(re.findall(r"[.,;:!?，。；：！？]", text))
    rough = cjk_chars + int(latin_words * 1.25) + int(punctuation * 0.2)
    return max(1, rough)


def _derive_article_type(text: str, *, code_ratio: float, heading_count: int) -> tuple[str, float]:
    sample = text[:12000].lower()
    research_hits = sum(1 for hint in _RESEARCH_HINTS if hint in sample)
    tutorial_hits = sum(1 for hint in _TUTORIAL_HINTS if hint in sample)
    news_hits = sum(1 for hint in _NEWS_HINTS if hint in sample)

    if code_ratio >= 0.26:
        return "code_heavy", min(0.98, 0.62 + code_ratio)
    if research_hits >= 2:
        return "research", min(0.95, 0.55 + research_hits * 0.10 + heading_count * 0.01)
    if tutorial_hits >= 2:
        return "tutorial", min(0.93, 0.50 + tutorial_hits * 0.11)
    if news_hits >= 2:
        return "news", min(0.9, 0.48 + news_hits * 0.12)
    return "general", 0.45


def _resolve_model_tier(*, token_count: int, code_ratio: float, table_count: int) -> str:
    if token_count <= 2500 and code_ratio < 0.12 and table_count <= 2:
        return "lite"
    return "standard"


def _resolve_stage_timeout(state: SummaryGraphState, *, stage: str) -> int:
    tier = state.get("model_tier", "standard")
    if stage == "map":
        return 60 if tier == "lite" else 90
    if stage == "validate":
        return 25
    return 90 if tier == "lite" else 120


async def _emit_token(token_sink, text: str) -> None:
    if not token_sink or not text:
        return
    try:
        maybe = token_sink(text)
        if asyncio.iscoroutine(maybe):
            await maybe
    except Exception:
        logger.debug("summary.token_sink_emit_failed")


def _extract_chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, list):
        parts = [str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content]
        return "".join(parts)
    return str(content or "")


async def _invoke_model(
    model,
    *,
    messages: list[Any],
    timeout_s: int,
    token_sink=None,
) -> tuple[str, int]:
    if token_sink:
        streamed_parts: list[str] = []
        t_stream = perf_counter()
        try:
            async with asyncio.timeout(timeout_s):
                async for chunk in model.astream(messages):
                    piece = _extract_chunk_text(chunk)
                    if not piece:
                        continue
                    streamed_parts.append(piece)
                    await _emit_token(token_sink, piece)
            streamed_text = "".join(streamed_parts).strip()
            logger.debug(
                "summary.llm_stream_done",
                elapsed_ms=_ms(t_stream),
                chars=len(streamed_text),
            )
            if streamed_text:
                return streamed_text, 0
        except Exception:
            logger.debug("summary.streaming_fallback_to_invoke")

    t_invoke = perf_counter()
    async with asyncio.timeout(timeout_s):
        resp = await model.ainvoke(messages)
    logger.debug(
        "summary.llm_invoke_done",
        elapsed_ms=_ms(t_invoke),
        chars=len(resp.content or ""),
    )
    return (resp.content or "").strip(), _extract_token_cost(resp)


def _build_validate_source_excerpt(state: SummaryGraphState) -> str:
    content = state.get("compressed_content") or state.get("clean_markdown") or ""
    content = content.strip()
    if not content:
        return ""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    excerpt = "\n".join(lines[:120])
    return excerpt[:_MAX_VALIDATE_SOURCE_CHARS]


def _heuristic_validate_summary(summary: str, source_excerpt: str, title: str) -> tuple[bool, list[str], float]:
    normalized_summary = (summary or "").strip()
    if not normalized_summary:
        return False, ["empty_summary"], 0.0
    summary_terms = _tokenize_for_validation(normalized_summary)
    source_terms = set(_tokenize_for_validation(f"{title}\n{source_excerpt}"))
    if not summary_terms or not source_terms:
        return False, ["insufficient_tokens"], 0.0
    overlap = sum(1 for term in summary_terms if term in source_terms) / max(len(summary_terms), 1)
    issues: list[str] = []
    # source_terms 过少（< 10）时 bigram overlap 仍不可靠，跳过检查交给 LLM validator
    if len(source_terms) >= 10 and overlap < 0.28:
        issues.append("low_source_overlap")
    if len(normalized_summary) < 80:
        issues.append("too_short")
    # 移除 2800 字硬底：对短文档（< 500 chars）应严格按比例限制
    max_summary_chars = max(400, int(len(source_excerpt) * 1.6))
    if len(normalized_summary) > max_summary_chars:
        issues.append("too_long")
    passed = not issues
    return passed, issues, overlap


def _tokenize_for_validation(text: str) -> list[str]:
    lowered = (text or "").lower()
    terms: list[str] = []
    # CJK: sliding 2-gram，避免整句话被当成一个 token 导致 overlap 永远为 0
    for run in re.findall(r"[\u4e00-\u9fff]+", lowered):
        if len(run) == 1:
            terms.append(run)
        else:
            for i in range(len(run) - 1):
                terms.append(run[i] + run[i + 1])
    # 拉丁/数字: 3+ 字符单词
    terms.extend(re.findall(r"[a-z0-9_]{3,}", lowered))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped


def _fallback_summary_text(state: SummaryGraphState) -> str:
    return ""


def _enforce_summary_budget(summary_text: str, state: SummaryGraphState) -> str:
    text = (summary_text or "").strip()
    if not text:
        return text
    source = (state.get("compressed_content") or state.get("clean_markdown") or "").strip()
    if not source:
        return text
    article_type = str(state.get("article_type") or "general")
    ratio_limit = 0.58
    if article_type == "code_heavy":
        ratio_limit = 0.62
    elif article_type == "research":
        ratio_limit = 0.60
    elif article_type == "news":
        ratio_limit = 0.52
    max_chars = max(300, int(len(source) * ratio_limit))
    if len(text) <= max_chars:
        return text
    cut = max_chars
    for marker in ("\n\n", "\n", "。", ". ", "；", ";"):
        pos = text.rfind(marker, max_chars // 2, max_chars)
        if pos > max_chars // 2:
            cut = pos + (0 if marker in ("\n\n", "\n") else len(marker))
            break
    return text[:cut].strip()


def _split_by_heading_blocks(content: str) -> list[str]:
    if not content:
        return []
    parts = re.split(r"(?m)(?=^#{1,6}\s+\S+)", content)
    normalized = [part.strip() for part in parts if part and part.strip()]
    return normalized or [content.strip()]


def _build_map_chunks(content: str, *, max_chunk_chars: int, max_chunks: int) -> list[str]:
    raw_sections = _split_by_heading_blocks(content)
    chunks: list[str] = []

    for section in raw_sections:
        if len(section) <= max_chunk_chars:
            chunks.append(section)
            continue
        start = 0
        while start < len(section):
            end = min(len(section), start + max_chunk_chars)
            piece = section[start:end]
            if end < len(section):
                break_pos = piece.rfind("\n\n")
                if break_pos > max_chunk_chars // 3:
                    end = start + break_pos
                    piece = section[start:end]
            trimmed = piece.strip()
            if trimmed:
                chunks.append(trimmed)
            start = end

    if len(chunks) <= max_chunks:
        return chunks

    kept = chunks[: max_chunks - 1]
    merged_tail = "\n\n".join(chunks[max_chunks - 1 :]).strip()
    if merged_tail:
        kept.append(merged_tail)
    return kept


# ========== Node 1: analyze_content ==========


def analyze_content(state: SummaryGraphState) -> dict[str, Any]:
    """分析文章类型、统计内容指标、选择模型档位。"""
    t0 = perf_counter()
    text = state["clean_markdown"]
    total_chars = len(text)

    code_chars = sum(
        len(m.group(0))
        for m in re.finditer(r"```(?:\w+)?\n.*?```", text, re.DOTALL)
    )
    code_ratio = code_chars / max(total_chars, 1)
    table_count = len(re.findall(r"^\|.*\|$", text, re.MULTILINE)) // 3
    image_count = len(re.findall(r"!\[", text))
    heading_count = len(_HEADING_LINE_RE.findall(text))
    bullet_count = len(re.findall(r"(?m)^\s*[-*+]\s+\S+", text))
    token_count = _estimate_token_count(text)

    article_type, confidence = _derive_article_type(
        text,
        code_ratio=code_ratio,
        heading_count=heading_count,
    )
    model_tier = _resolve_model_tier(
        token_count=token_count,
        code_ratio=code_ratio,
        table_count=table_count,
    )
    summary_strategy = (
        "map_reduce"
        if token_count > get_settings().summary_map_reduce_threshold_tokens or heading_count >= 14
        else "direct"
    )

    observe_summary_stage(stage="analyze", status="ok", duration_ms=_ms(t0))
    observe_summary_model_tier(tier=model_tier)
    observe_summary_strategy(strategy=summary_strategy)
    logger.debug(
        "summary.node_analyze_content",
        elapsed_ms=_ms(t0),
        article_type=article_type,
        model_tier=model_tier,
        summary_strategy=summary_strategy,
        token_count=token_count,
        heading_count=heading_count,
        code_ratio=round(code_ratio, 3),
    )

    return {
        "article_type": article_type,
        "article_type_confidence": round(confidence, 3),
        "content_stats": {
            "token_count": token_count,
            "code_ratio": round(code_ratio, 3),
            "table_count": table_count,
            "image_count": image_count,
            "heading_count": heading_count,
            "bullet_count": bullet_count,
        },
        "model_tier": model_tier,
        "summary_strategy": summary_strategy,
    }


# ========== Node 2: compress_content_node ==========


async def compress_content_node(state: SummaryGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    settings = get_settings()
    original = state["clean_markdown"]
    article_id = str(state.get("article_id") or "")
    content_hash = str(state.get("content_hash") or "")
    article_type = state.get("article_type", "general")
    db_session = state.get("db_session")

    if db_session and article_id and content_hash:
        t_db_read = perf_counter()
        try:
            cached = await repo.get_compression_cache(
                db_session,
                article_id=article_id,
                content_hash=content_hash,
                prompt_version=PROMPT_VERSION,
                article_type=article_type,
                compress_version=_COMPRESS_VERSION,
                compress_code_blocks=bool(settings.summary_compress_code_blocks),
            )
            logger.debug(
                "summary.compress_db_read",
                elapsed_ms=_ms(t_db_read),
                cache_hit=cached is not None,
            )
            if cached and str(cached.compressed_content or "").strip():
                observe_summary_stage(stage="compress", status="cache_hit", duration_ms=_ms(t0))
                logger.debug("summary.node_compress_content", elapsed_ms=_ms(t0), cache_hit=True)
                return {
                    "compressed_content": str(cached.compressed_content),
                    "compression_cache_hit": True,
                }
        except Exception as exc:
            logger.debug(
                "summary.compress_cache_read_failed",
                elapsed_ms=_ms(t_db_read),
                error=str(exc)[:160],
            )

    t_compress = perf_counter()
    compressed = compress_content(
        original,
        compress_code=settings.summary_compress_code_blocks,
        article_type=article_type,
    )
    logger.debug(
        "summary.compress_cpu",
        elapsed_ms=_ms(t_compress),
        original_chars=len(original),
        compressed_chars=len(compressed),
        ratio=round(len(compressed) / max(len(original), 1), 3),
    )

    if db_session and article_id and content_hash and compressed:
        t_db_write = perf_counter()
        try:
            await repo.save_compression_cache(
                db_session,
                article_id=article_id,
                content_hash=content_hash,
                prompt_version=PROMPT_VERSION,
                article_type=article_type,
                compress_version=_COMPRESS_VERSION,
                compress_code_blocks=bool(settings.summary_compress_code_blocks),
                compressed_content=compressed,
                original_length=len(original),
                compressed_length=len(compressed),
            )
            await db_session.commit()
            logger.debug("summary.compress_db_write", elapsed_ms=_ms(t_db_write))
        except Exception as exc:
            logger.debug(
                "summary.compress_cache_write_failed",
                elapsed_ms=_ms(t_db_write),
                error=str(exc)[:160],
            )
            try:
                await db_session.rollback()
            except Exception:
                logger.debug("summary.compress_cache_write_rollback_failed")

    observe_summary_stage(stage="compress", status="ok", duration_ms=_ms(t0))
    if original:
        observe_summary_compression_ratio(ratio=len(compressed) / max(len(original), 1))
    logger.debug(
        "summary.node_compress_content",
        elapsed_ms=_ms(t0),
        cache_hit=False,
        original_chars=len(original),
        compressed_chars=len(compressed),
    )

    return {"compressed_content": compressed, "compression_cache_hit": False}


# ========== Node 3: direct_summarize ==========


async def direct_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """直接调用 LLM 生成摘要。"""
    t0 = perf_counter()
    model = _resolve_model(state)
    if model is None:
        observe_summary_stage(stage="direct_summarize", status="skip", duration_ms=_ms(t0))
        return {
            "summary_text": _fallback_summary_text(state),
            "fallback_used": True,
            "fallback_reason": "model_missing",
            "summary_strategy": "direct",
        }

    article_type = state.get("article_type", "general")
    user_template = USER_PROMPTS.get(article_type, USER_PROMPTS["general"])

    system = SYSTEM_PROMPT
    if state.get("language", "auto") == "zh":
        system += "\n\nIMPORTANT: Write the summary in 简体中文."

    content = state.get("compressed_content") or state["clean_markdown"]
    messages = [
        SystemMessage(content=system),
        HumanMessage(content=user_template.format(
            title=state.get("title", ""),
            content=content[:64000],
        )),
    ]

    t_llm = perf_counter()
    try:
        text, tokens = await _invoke_model(
            model,
            messages=messages,
            timeout_s=_resolve_stage_timeout(state, stage="direct"),
            token_sink=state.get("token_sink"),
        )
        logger.info(
            "summary.llm_direct_done",
            elapsed_ms=_ms(t_llm),
            tokens=tokens,
            chars=len(text),
            article_id=str(state.get("article_id") or ""),
        )
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="direct_summarize", status="ok", duration_ms=_ms(t0))
        if text:
            text = _enforce_summary_budget(text, state)
            return {
                "summary_text": text,
                "fallback_used": False,
                "fallback_reason": "",
                "summary_strategy": "direct",
            }
    except Exception as exc:
        logger.exception("summary.direct_failed", elapsed_ms=_ms(t_llm), error=str(exc)[:200])

    observe_summary_stage(stage="direct_summarize", status="error", duration_ms=_ms(t0))
    return {
        "summary_text": _fallback_summary_text(state),
        "fallback_used": True,
        "fallback_reason": "direct_failed",
        "summary_strategy": "direct",
    }


# ========== Node 4: map_split ==========


def map_split(state: SummaryGraphState) -> dict[str, Any]:
    """按标题优先切块，供 map 阶段摘要。"""
    t0 = perf_counter()
    content = state.get("compressed_content") or state["clean_markdown"]
    settings = get_settings()
    threshold = int(settings.summary_map_reduce_threshold_tokens)

    max_chunk_chars = 12000 if threshold <= 8000 else 14000
    max_chunks = 8
    chunks = _build_map_chunks(
        content,
        max_chunk_chars=max_chunk_chars,
        max_chunks=max_chunks,
    )

    observe_summary_stage(stage="map_split", status="ok", duration_ms=_ms(t0))
    logger.debug(
        "summary.node_map_split",
        elapsed_ms=_ms(t0),
        chunk_count=len(chunks),
        article_id=str(state.get("article_id") or ""),
    )
    return {"map_chunks": chunks, "summary_strategy": "map_reduce"}


# ========== Node 5: map_summarize ==========


async def map_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """对单个 map chunk 生成摘要。"""
    t0 = perf_counter()
    model = build_lite_llm() or _resolve_model(state)
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

    t_llm = perf_counter()
    try:
        text, tokens = await _invoke_model(
            model,
            messages=messages,
            timeout_s=_resolve_stage_timeout(state, stage="map"),
        )
        logger.info(
            "summary.llm_map_done",
            elapsed_ms=_ms(t_llm),
            tokens=tokens,
            chars=len(text),
            article_id=str(state.get("article_id") or ""),
        )
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="map_summarize", status="ok", duration_ms=_ms(t0))
        return {"chunk_summaries": [text]}
    except Exception as exc:
        logger.warning("summary.map_failed", elapsed_ms=_ms(t_llm), error=str(exc)[:200])
        observe_summary_stage(stage="map_summarize", status="error", duration_ms=_ms(t0))
        return {"chunk_summaries": [""]}


# ========== Node 6: reduce_summarize ==========


async def reduce_summarize(state: SummaryGraphState) -> dict[str, Any]:
    """合并 map 阶段的中间摘要为最终摘要。"""
    t0 = perf_counter()
    model = _resolve_model(state)
    if model is None:
        observe_summary_stage(stage="reduce_summarize", status="skip", duration_ms=_ms(t0))
        fallback = "\n\n".join(item for item in state.get("chunk_summaries", []) if item).strip()
        return {
            "summary_text": fallback or _fallback_summary_text(state),
            "fallback_used": True,
            "fallback_reason": "reduce_model_missing",
            "summary_strategy": "map_reduce",
        }

    summaries_text = "\n\n---\n\n".join(
        f"[Section {index + 1}]\n{item}"
        for index, item in enumerate(state.get("chunk_summaries", []))
        if item
    )

    system = SYSTEM_PROMPT
    if state.get("language") == "zh":
        system += "\n\nIMPORTANT: Write the summary in 简体中文."

    messages = [
        SystemMessage(content=system),
        HumanMessage(content=REDUCE_PROMPT.format(
            title=state.get("title", ""),
            summaries=summaries_text[:36000],
        )),
    ]

    t_llm = perf_counter()
    try:
        text, tokens = await _invoke_model(
            model,
            messages=messages,
            timeout_s=_resolve_stage_timeout(state, stage="reduce"),
            token_sink=state.get("token_sink"),
        )
        logger.info(
            "summary.llm_reduce_done",
            elapsed_ms=_ms(t_llm),
            tokens=tokens,
            chars=len(text),
            article_id=str(state.get("article_id") or ""),
        )
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        observe_summary_stage(stage="reduce_summarize", status="ok", duration_ms=_ms(t0))
        if text:
            text = _enforce_summary_budget(text, state)
            return {
                "summary_text": text,
                "fallback_used": False,
                "fallback_reason": "",
                "summary_strategy": "map_reduce",
            }
    except Exception as exc:
        logger.warning("summary.reduce_failed", elapsed_ms=_ms(t_llm), error=str(exc)[:200])

    observe_summary_stage(stage="reduce_summarize", status="error", duration_ms=_ms(t0))
    fallback = "\n\n".join(item for item in state.get("chunk_summaries", []) if item).strip()
    return {
        "summary_text": fallback or _fallback_summary_text(state),
        "fallback_used": True,
        "fallback_reason": "reduce_failed",
        "summary_strategy": "map_reduce",
    }


# ========== Node 7: validate_summary ==========


async def validate_summary(state: SummaryGraphState) -> dict[str, Any]:
    """用 lite_model 校验摘要质量。"""
    t0 = perf_counter()
    retry_count = state.get("retry_count", 0) + 1
    summary = state.get("summary_text", "").strip()
    source_excerpt = _build_validate_source_excerpt(state)

    # 极短文章（< 400 chars 源内容）自动通过：LLM 必须扩写，overlap 天然为 0，
    # 继续走 LLM validator 只会浪费 2 次 ~7s 调用且必然失败。
    if source_excerpt and len(source_excerpt) < 400 and summary:
        logger.debug(
            "summary.validate_short_article_skip",
            source_chars=len(source_excerpt),
            summary_chars=len(summary),
        )
        observe_summary_stage(stage="validate", status="short_article_skip", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=True)
        return {
            "validation_passed": True,
            "validation_issues": ["short_article_skip"],
            "retry_count": retry_count,
        }

    t_heuristic = perf_counter()
    heuristic_passed, heuristic_issues, heuristic_overlap = _heuristic_validate_summary(
        summary,
        source_excerpt,
        str(state.get("title") or ""),
    )
    logger.debug(
        "summary.validate_heuristic_done",
        elapsed_ms=_ms(t_heuristic),
        passed=heuristic_passed,
        overlap=round(heuristic_overlap, 3),
        issues=heuristic_issues,
    )

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
        observe_summary_validation_result(passed=heuristic_passed)
        return {
            "validation_passed": heuristic_passed,
            "validation_issues": heuristic_issues + ["validator_skipped_heuristic"],
            "retry_count": retry_count,
        }

    # Heuristic 已经足够可靠时直接通过，避免 validator 额外高延迟。
    if heuristic_passed and heuristic_overlap >= 0.42:
        observe_summary_stage(stage="validate", status="heuristic_ok", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=True)
        return {
            "validation_passed": True,
            "validation_issues": ["validator_short_circuit_heuristic"],
            "retry_count": retry_count,
        }

    # 明显长度异常时直接 fail-closed，避免浪费一次慢校验调用。
    if "too_short" in heuristic_issues or "too_long" in heuristic_issues:
        observe_summary_stage(stage="validate", status="heuristic_reject", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=False)
        for issue in heuristic_issues[:3]:
            observe_summary_judge_reject(reason=issue[:32])
        return {
            "validation_passed": False,
            "validation_issues": heuristic_issues + ["validator_short_circuit_heuristic"],
            "retry_count": max(retry_count, get_settings().summary_max_retries),
        }

    messages = [
        SystemMessage(content="You are a summary quality evaluator. Return ONLY valid JSON."),
        HumanMessage(content=VALIDATE_PROMPT.format(
            title=state.get("title", ""),
            summary=summary,
            source_excerpt=source_excerpt,
        )),
    ]

    t_llm = perf_counter()
    try:
        text, tokens = await _invoke_model(
            model,
            messages=messages,
            timeout_s=_resolve_stage_timeout(state, stage="validate"),
        )
        logger.debug(
            "summary.llm_validate_done",
            elapsed_ms=_ms(t_llm),
            tokens=tokens,
            article_id=str(state.get("article_id") or ""),
        )
        if tokens:
            observe_summary_token_cost(tokens=tokens)
        raw = text.strip()
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError("judge_output_not_json")
        result = json.loads(json_match.group(0))
        passed = bool(result.get("passed", False))
        issues_raw = result.get("issues", [])
        issues = [str(item).strip() for item in issues_raw if str(item).strip()]
        observe_summary_stage(stage="validate", status="ok", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=passed)
        if not passed:
            for issue in issues[:3]:
                observe_summary_judge_reject(reason=issue[:32])
        return {"validation_passed": passed, "validation_issues": issues, "retry_count": retry_count}
    except Exception as exc:
        logger.debug("summary.validate_parse_failed", error=str(exc)[:160])
        observe_summary_stage(stage="validate", status="fallback", duration_ms=_ms(t0))
        observe_summary_validation_result(passed=heuristic_passed)
        if not heuristic_passed:
            for issue in heuristic_issues[:3]:
                observe_summary_judge_reject(reason=issue[:32])
        return {
            "validation_passed": heuristic_passed,
            "validation_issues": heuristic_issues + ["validator_fallback_heuristic"],
            "retry_count": max(retry_count, get_settings().summary_max_retries),
        }

    observe_summary_stage(stage="validate", status="error", duration_ms=_ms(t0))
    observe_summary_validation_result(passed=False)
    observe_summary_judge_reject(reason="invalid_judge_output")
    return {
        "validation_passed": False,
        "validation_issues": ["invalid_judge_output"],
        "retry_count": max(retry_count, get_settings().summary_max_retries),
    }


# ── 工具函数 ──────────────────────────────────────────────────────


def _resolve_model(state: SummaryGraphState):
    tier = state.get("model_tier", "standard")
    if tier == "lite":
        lite = build_lite_llm()
        if lite is not None:
            return lite
    user = state.get("user")
    return build_user_chat_model(user) if user else None


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
