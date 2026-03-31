"""Phase 3b — 增强层：TOC fallback + 摘要预热。"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from time import perf_counter

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.types import RemarkResult, TOCNode

logger = structlog.get_logger(__name__)
_SUMMARY_WARM_TIMEOUT_SECONDS = 60 
_MAX_TOC_ITEMS = 60
_MAX_TOC_CONTEXT_CHARS = 6000
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


async def ensure_toc(
    *,
    remark: RemarkResult,
    title: str,
    language: str | None = None,
) -> None:
    """确保 remark.toc 有值（优先 markdown headings，其次 LLM fallback）。"""

    if remark.toc:
        logger.debug("enhance.toc_already_present", count=len(remark.toc))
        return

    t0 = perf_counter()
    toc_from_markdown = _extract_toc_from_markdown(remark.clean_markdown)
    if toc_from_markdown:
        remark.toc = toc_from_markdown
        logger.info(
            "enhance.toc_built_from_markdown",
            count=len(remark.toc),
            duration_ms=round((perf_counter() - t0) * 1000, 2),
        )
        return

    llm_t0 = perf_counter()
    llm_toc = await _generate_toc_via_llm(
        clean_markdown=remark.clean_markdown,
        title=title,
        language=language,
    )
    llm_ms = round((perf_counter() - llm_t0) * 1000, 2)
    if llm_toc:
        remark.toc = llm_toc
        logger.info(
            "enhance.toc_built_from_llm",
            count=len(remark.toc),
            llm_duration_ms=llm_ms,
            total_duration_ms=round((perf_counter() - t0) * 1000, 2),
        )
    else:
        logger.info(
            "enhance.toc_missing_after_fallback",
            llm_duration_ms=llm_ms,
            total_duration_ms=round((perf_counter() - t0) * 1000, 2),
        )


async def warm_summary(
    db: AsyncSession,
    *,
    remark: RemarkResult,
    article_id: str,
    title: str,
    language: str | None = None,
    user=None,
) -> None:
    """预热摘要缓存；失败不抛出（非关键路径）。"""

    if not remark.clean_markdown:
        return
    t0 = perf_counter()
    try:
        from app.modules.agent.summary.service import generate_summary

        await asyncio.wait_for(
            generate_summary(
                db,
                article_id=article_id,
                title=title,
                clean_markdown=remark.clean_markdown,
                language=language or "auto",
                user=user,
            ),
            timeout=_SUMMARY_WARM_TIMEOUT_SECONDS,
        )
        logger.debug(
            "enhance.summary_warmed",
            duration_ms=round((perf_counter() - t0) * 1000, 2),
            markdown_chars=len(remark.clean_markdown),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "enhance.summary_timeout",
            timeout_s=_SUMMARY_WARM_TIMEOUT_SECONDS,
            elapsed_ms=round((perf_counter() - t0) * 1000, 2),
        )
    except Exception as exc:
        logger.warning(
            "enhance.summary_failed",
            error=str(exc),
            duration_ms=round((perf_counter() - t0) * 1000, 2),
        )


async def enhance(
    db: AsyncSession,
    *,
    remark: RemarkResult,
    article_id: str,
    title: str,
    language: str | None = None,
    user=None,
) -> None:
    """兼容入口：先补 TOC，再预热摘要。"""

    await ensure_toc(remark=remark, title=title, language=language)
    await warm_summary(
        db,
        remark=remark,
        article_id=article_id,
        title=title,
        language=language,
        user=user,
    )


def _extract_toc_from_markdown(clean_markdown: str) -> list[TOCNode]:
    if not clean_markdown.strip():
        return []
    toc: list[TOCNode] = []
    anchor_seen: dict[str, int] = {}

    for line in clean_markdown.splitlines():
        matched = _HEADING_RE.match(line.strip())
        if not matched:
            continue
        marks, raw_title = matched.groups()
        title = raw_title.strip()
        if not title:
            continue
        level = min(6, max(1, len(marks)))
        anchor = _unique_anchor(_slugify(title), anchor_seen)
        toc.append(
            TOCNode(
                id=anchor,
                title=title,
                level=level,
                anchor=anchor,
            )
        )
        if len(toc) >= _MAX_TOC_ITEMS:
            break
    return toc


async def _generate_toc_via_llm(
    *,
    clean_markdown: str,
    title: str,
    language: str | None = None,
) -> list[TOCNode]:
    if not clean_markdown.strip():
        return []

    try:
        from app.infra.ai.lite_models import build_lite_llm

        model = build_lite_llm()
        if model is None:
            return []

        prompt_lang = language or "zh"
        truncated = clean_markdown[:_MAX_TOC_CONTEXT_CHARS]
        messages = [
            SystemMessage(
                content=(
                    "你是文档结构抽取器。请基于正文抽取目录，输出 JSON 数组，不要输出其他文本。"
                    '每个元素格式为 {"title":"章节名","level":1-4}。'
                    f"最多输出 {_MAX_TOC_ITEMS} 项。"
                )
            ),
            HumanMessage(
                content=(
                    f"文档标题：{title or '未命名文档'}\n"
                    f"语言：{prompt_lang}\n"
                    f"正文片段：\n{truncated}"
                )
            ),
        ]
        resp = await model.ainvoke(messages)
        content = str(resp.content or "").strip()
        return _parse_llm_toc_json(content)
    except Exception as exc:
        logger.warning("enhance.toc_llm_failed", error=str(exc)[:200])
        return []


def _parse_llm_toc_json(raw: str) -> list[TOCNode]:
    if not raw:
        return []

    block = raw
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        block = raw[start : end + 1]

    try:
        items = json.loads(block)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []

    toc: list[TOCNode] = []
    anchor_seen: dict[str, int] = {}
    for idx, item in enumerate(items[:_MAX_TOC_ITEMS]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        level_raw = item.get("level", 1)
        try:
            level = int(level_raw)
        except (TypeError, ValueError):
            level = 1
        level = max(1, min(4, level))
        anchor = _unique_anchor(_slugify(title) or f"section-{idx+1}", anchor_seen)
        toc.append(TOCNode(id=anchor, title=title, level=level, anchor=anchor))
    return toc


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    cleaned = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^\w\s-]", "", cleaned, flags=re.UNICODE).strip().lower()
    cleaned = re.sub(r"[\s_-]+", "-", cleaned)
    return cleaned or "section"


def _unique_anchor(anchor: str, seen: dict[str, int]) -> str:
    count = seen.get(anchor, 0)
    seen[anchor] = count + 1
    if count == 0:
        return anchor
    return f"{anchor}-{count+1}"
