"""Phase 4.1 — Chunk 上下文增强。

为每个 chunk 生成 contextualized_text，拼接 notebook/article/heading 前缀，
对"指代不清"的 chunk 用 lite_model 补充 1-2 句上下文。
"""

from __future__ import annotations

import re
from time import perf_counter

import structlog

from app.modules.ingest.types import ChunkDraft, TOCNode

logger = structlog.get_logger(__name__)

_PRONOUN_PATTERN = re.compile(
    r"^.{0,60}(它|这|该|上述|此|其|本节|上面|前文|以下|these|this|that|its|the above|aforementioned)",
    re.IGNORECASE,
)


def _build_heading_path(toc: list[TOCNode], section_id: str | None) -> str:
    if not section_id or not toc:
        return ""
    toc_map = {n.id: n for n in toc}
    node = toc_map.get(section_id)
    return node.title if node else ""


def _needs_generative_context(text: str) -> bool:
    """规则判定 chunk 是否"指代不清"。"""
    first_80 = text[:80]
    return bool(_PRONOUN_PATTERN.search(first_80))


_CTX_LLM_SLOW_MS = 5_000  # 单次 LLM 调用超过此值打 warning


async def _generate_context_sentence(
    text: str,
    *,
    article_title: str,
    heading: str,
) -> str:
    """用 lite_model 生成 1-2 句上下文描述。失败时返回空字符串。"""
    t0 = perf_counter()
    try:
        from app.infra.ai.lite_models import build_lite_llm

        model = build_lite_llm()
        if model is None:
            return ""

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=(
                "根据文章标题和章节标题，为以下文本片段写一句简短的上下文背景（不超过 40 字），"
                "使读者不需要看原文就能理解这段内容在说什么。只输出这一句话。"
            )),
            HumanMessage(content=(
                f"文章标题：{article_title}\n章节：{heading}\n\n片段：\n{text[:500]}"
            )),
        ]
        resp = await model.ainvoke(messages)
        duration_ms = round((perf_counter() - t0) * 1000, 2)
        result = (resp.content or "").strip()
        log_fn = logger.warning if duration_ms > _CTX_LLM_SLOW_MS else logger.debug
        log_fn(
            "contextualize.llm_call_done",
            duration_ms=duration_ms,
            result_chars=len(result),
        )
        return result
    except Exception as exc:
        duration_ms = round((perf_counter() - t0) * 1000, 2)
        logger.debug("contextualize.llm_failed", error=str(exc)[:120], duration_ms=duration_ms)
        return ""


async def contextualize_chunks(
    chunks: list[ChunkDraft],
    *,
    notebook_title: str = "",
    article_title: str = "",
    toc: list[TOCNode] | None = None,
    clean_markdown: str = "",
) -> list[ChunkDraft]:
    """为每个 chunk 填充 contextualized_text。"""

    if not chunks:
        return chunks

    toc_list = toc or []
    total_t0 = perf_counter()
    llm_call_count = 0
    llm_total_ms = 0.0

    for chunk in chunks:
        heading = (
            chunk.heading_title
            or _build_heading_path(toc_list, chunk.section_id)
        )

        # ====== step 1 拼接结构化前缀 ======
        prefix_parts: list[str] = []
        if notebook_title:
            prefix_parts.append(f"笔记本：{notebook_title}")
        if article_title:
            prefix_parts.append(f"文章：{article_title}")
        if heading:
            prefix_parts.append(f"章节：{heading}")
        prefix = " > ".join(prefix_parts)

        # ====== step 2 可选生成式上下文 ======
        gen_ctx = ""
        if _needs_generative_context(chunk.text):
            llm_t0 = perf_counter()
            gen_ctx = await _generate_context_sentence(
                chunk.text,
                article_title=article_title,
                heading=heading,
            )
            llm_call_count += 1
            llm_total_ms += round((perf_counter() - llm_t0) * 1000, 2)

        # ====== step 3 组装 ======
        parts: list[str] = []
        if prefix:
            parts.append(prefix)
        if gen_ctx:
            parts.append(gen_ctx)
        parts.append(chunk.text)

        chunk.contextualized_text = "\n".join(parts)

    total_ms = round((perf_counter() - total_t0) * 1000, 2)
    logger.info(
        "contextualize.complete",
        total=len(chunks),
        llm_calls=llm_call_count,
        llm_total_ms=round(llm_total_ms, 2),
        llm_avg_ms=round(llm_total_ms / llm_call_count, 2) if llm_call_count else 0,
        prefix_only_count=len(chunks) - llm_call_count,
        total_ms=total_ms,
    )
    return chunks
