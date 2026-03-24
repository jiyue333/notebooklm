"""MIME 检测客户端 — 基于 python-magic (libmagic)。

轻量替代 Apache Tika，无需 JVM。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import magic
import structlog

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class DetectResult:
    mime_type: str = "application/octet-stream"


def detect_mime(raw_bytes: bytes) -> str:
    """同步检测 MIME 类型。"""
    try:
        return magic.from_buffer(raw_bytes, mime=True)
    except Exception as exc:
        logger.warning("magic.detect_failed", error=str(exc))
        return "application/octet-stream"


async def detect_mime_async(raw_bytes: bytes) -> str:
    """异步检测 MIME 类型（run_in_executor）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, detect_mime, raw_bytes)
