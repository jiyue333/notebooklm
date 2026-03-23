"""Phase 3a — 规范化层：通过 Node.js remark subprocess 处理 markdown。

输入 raw markdown → 输出 RemarkResult (AST + clean markdown + HTML + TOC + 阅读时间)。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import structlog

from app.core.config import get_settings
from app.modules.ingest.types import RemarkResult, TOCNode

logger = structlog.get_logger(__name__)

_DEFAULT_SCRIPT = Path(__file__).resolve().parents[4] / "tools" / "remark-processor" / "index.mjs"


async def process_markdown(raw_markdown: str) -> RemarkResult:
    """调用 Node.js remark-processor，返回规范化结果。"""

    settings = get_settings()
    script_path = settings.remark_processor_path or str(_DEFAULT_SCRIPT)
    timeout = settings.remark_timeout_seconds

    payload = json.dumps({"markdown": raw_markdown})

    proc = await asyncio.create_subprocess_exec(
        "node", script_path,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(payload.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        logger.warning("normalize.remark_timeout", timeout=timeout)
        return _fallback_result(raw_markdown)

    if proc.returncode != 0:
        err_msg = stderr.decode("utf-8", errors="replace")[:500]
        logger.warning("normalize.remark_failed", returncode=proc.returncode, stderr=err_msg)
        return _fallback_result(raw_markdown)

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        logger.warning("normalize.remark_json_error", error=str(exc))
        return _fallback_result(raw_markdown)

    toc_nodes = [
        TOCNode(
            id=item.get("id", ""),
            title=item.get("title", ""),
            level=item.get("level", 1),
            anchor=item.get("anchor", ""),
        )
        for item in data.get("toc", [])
    ]

    rt = data.get("readingTime", {})

    return RemarkResult(
        mdast=data.get("mdast", {}),
        clean_markdown=data.get("cleanMarkdown", raw_markdown),
        html=data.get("html", ""),
        toc=toc_nodes,
        reading_time_minutes=rt.get("minutes", 1),
        reading_time_words=rt.get("words", 0),
        fixes_applied=data.get("fixes", {}).get("appliedCount", 0),
    )


def _fallback_result(raw_markdown: str) -> RemarkResult:
    """remark 不可用时的降级结果。"""
    return RemarkResult(
        mdast={},
        clean_markdown=raw_markdown,
        html="",
        toc=[],
        reading_time_minutes=max(1, len(raw_markdown) // 1500),
        reading_time_words=len(raw_markdown.split()),
        fixes_applied=0,
    )
