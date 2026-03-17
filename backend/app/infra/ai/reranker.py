"""Rerank 客户端：带并发控制的 /rerank 封装。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import structlog
from langsmith import traceable

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RerankResult:
    """单条 rerank 结果。"""

    index: int
    relevance_score: float


class RerankClient:
    """异步 rerank 客户端，内置并发节流。"""

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._api_url = s.rerank_model_api_url.rstrip("/")
        self._api_key = s.rerank_model_api_key or ""
        self._model = s.rerank_model
        self._timeout = float(s.rerank_timeout)
        self._semaphore = asyncio.Semaphore(s.rerank_max_concurrency)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        *,
        top_n: int | None = None,
    ) -> list[RerankResult]:
        """对候选文档做 rerank，并返回按分数排序的结果。"""

        if not documents:
            return []

        body: dict = {
            "model": self._model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            body["top_n"] = top_n

        # 只把裁剪后的输入和概要信息送进 LangSmith，避免整批文档全文进入 trace。
        data = await self._traced_rerank_request(
            body=body,
            query_preview=_truncate_text(query, limit=200),
            document_count=len(documents),
            top_n=top_n,
        )

        raw_results = data.get("results") or data.get("data") or []
        items = [
            RerankResult(
                index=r.get("index", i),
                relevance_score=float(r.get("relevance_score", 0.0)),
            )
            for i, r in enumerate(raw_results)
        ]
        items.sort(key=lambda x: x.relevance_score, reverse=True)
        return items

    @traceable(name="reranker.request", run_type="tool")
    async def _traced_rerank_request(
        self,
        *,
        body: dict,
        query_preview: str,
        document_count: int,
        top_n: int | None,
    ) -> dict:
        """发送带追踪的 rerank 请求。"""
        async with self._semaphore:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._api_url}/rerank",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

        results = data.get("results") or data.get("data") or []
        logger.info(
            "reranker.request_completed",
            model=self._model,
            query_preview=query_preview,
            document_count=document_count,
            top_n=top_n,
            result_count=len(results),
        )
        return data


_client: RerankClient | None = None


def build_reranker(settings: Settings | None = None) -> RerankClient | None:
    """构建（或复用）RerankClient；未配置时返回 `None`。"""

    global _client
    s = settings or get_settings()
    if not s.rerank_model_api_key:
        return None
    if _client is None:
        _client = RerankClient(s)
    return _client


def _truncate_text(text: str, *, limit: int) -> str:
    value = text.strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."
