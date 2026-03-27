"""Phase 3b — 增强层：TOC LLM fallback + 摘要调用。"""

from __future__ import annotations

import asyncio

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ingest.types import RemarkResult

logger = structlog.get_logger(__name__)
_SUMMARY_WARM_TIMEOUT_SECONDS = 5


async def enhance(
    db: AsyncSession,
    *,
    remark: RemarkResult,
    article_id: str,
    title: str,
    language: str | None = None,
    user=None,
) -> None:
    """在 remark 结果基础上做增强。直接修改 remark 对象，无返回值。

    1. TOC 为空时尝试 LLM fallback
    2. 调用 summary 服务写入缓存
    """

    # ========== step 1 TOC LLM fallback ==========
    if not remark.toc:
        logger.info("enhance.toc_empty_trying_llm")
        # TODO: 实现 LLM 生成 TOC，当前先跳过

    # ========== step 2 摘要 ==========
    if remark.clean_markdown:
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
        except asyncio.TimeoutError:
            logger.warning("enhance.summary_timeout", timeout_s=_SUMMARY_WARM_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("enhance.summary_failed", error=str(exc))
