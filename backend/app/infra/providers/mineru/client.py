"""MinerU Cloud API 客户端 — 统一使用 batch API。

两种 batch 路径:
  1. URL batch   POST /extract/task/batch  — URL 来源，MinerU 自行下载
  2. 文件 batch  POST /file-urls/batch     — 本地文件上传

两者共用:
  - 轮询  GET /extract-results/batch/{batch_id}
  - 下载  GET full_zip_url → ZIP → full.md
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from dataclasses import dataclass, field

import httpx
import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class MinerUCloudError(Exception):
    pass


@dataclass(slots=True)
class BatchItemResult:
    """batch 轮询中单个条目的结果。"""
    data_id: str
    state: str                    # done | failed | running | pending
    zip_url: str | None = None
    err_msg: str | None = None


class MinerUCloudClient:
    """通过 MinerU Cloud batch REST API 将文档转为 Markdown。"""

    def __init__(self, settings: Settings | None = None) -> None:
        s = settings or get_settings()
        self._base_url = s.mineru_api_base_url.rstrip("/")
        self._token = s.mineru_api_token
        self._default_model = s.mineru_default_model
        self._poll_interval = s.mineru_poll_interval_seconds
        self._poll_timeout = s.mineru_poll_timeout_seconds

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # ── 提交 ──────────────────────────────────────────────────────────

    async def submit_url_batch(
        self,
        items: list[dict],
        *,
        model_version: str | None = None,
    ) -> str:
        """URL batch: POST /extract/task/batch → batch_id。

        items: [{"url": "https://...", "data_id": "article-xxx"}, ...]
        """
        model = model_version or self._default_model
        body = {"files": items, "model_version": model}

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{self._base_url}/extract/task/batch",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise MinerUCloudError(f"URL batch 提交失败: {data.get('msg')}")
            batch_id = data["data"]["batch_id"]
            logger.info("mineru.url_batch_submitted", batch_id=batch_id, count=len(items))
            return batch_id

    async def submit_file_batch(
        self,
        items: list[dict],
        *,
        model_version: str | None = None,
    ) -> tuple[str, list[str]]:
        """文件 batch: POST /file-urls/batch → (batch_id, upload_urls)。

        items: [{"name": "paper.pdf", "data_id": "article-xxx"}, ...]
        返回 upload_urls 与 items 一一对应，调用方需逐个 PUT 上传。
        """
        model = model_version or self._default_model
        body = {"files": items, "model_version": model}

        async with httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(
                f"{self._base_url}/file-urls/batch",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise MinerUCloudError(f"文件 batch 提交失败: {data.get('msg')}")
            batch_id = data["data"]["batch_id"]
            upload_urls = data["data"]["file_urls"]
            logger.info("mineru.file_batch_submitted", batch_id=batch_id, count=len(items))
            return batch_id, upload_urls

    async def upload_file(self, upload_url: str, raw_bytes: bytes) -> None:
        """PUT 上传单个文件到 MinerU 提供的预签名 URL。"""
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.put(upload_url, content=raw_bytes)
            resp.raise_for_status()
        logger.debug("mineru.file_uploaded", size=len(raw_bytes))

    # ── 轮询 ──────────────────────────────────────────────────────────

    async def poll_batch(
        self,
        batch_id: str,
        *,
        target_data_id: str | None = None,
    ) -> list[BatchItemResult]:
        """轮询 batch 直到全部终态 (done/failed)，返回所有条目结果。

        target_data_id: 若只关心一个条目，该条目终态后立即返回。
        """
        url = f"{self._base_url}/extract-results/batch/{batch_id}"
        elapsed = 0.0

        async with httpx.AsyncClient(timeout=30) as http:
            while elapsed < self._poll_timeout:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval

                resp = await http.get(url, headers=self._headers())
                resp.raise_for_status()
                raw_results = resp.json().get("data", {}).get("extract_result", [])
                if not raw_results:
                    continue

                items = [
                    BatchItemResult(
                        data_id=r.get("data_id", ""),
                        state=r.get("state", ""),
                        zip_url=r.get("full_zip_url"),
                        err_msg=r.get("err_msg"),
                    )
                    for r in raw_results
                ]

                # 只关心单条目时，该条目终态即返回
                if target_data_id:
                    target = next((i for i in items if i.data_id == target_data_id), None)
                    if target and target.state in {"done", "failed"}:
                        return [target]

                # 全部终态
                if all(i.state in {"done", "failed"} for i in items):
                    return items

                running = sum(1 for i in items if i.state not in {"done", "failed"})
                logger.debug("mineru.polling_batch", batch_id=batch_id, running=running, elapsed=elapsed)

        logger.warning("mineru.batch_poll_timeout", batch_id=batch_id)
        return []

    # ── 下载 ──────────────────────────────────────────────────────────

    async def download_markdown(self, zip_url: str) -> str | None:
        """下载 ZIP 并提取 full.md。"""
        async with httpx.AsyncClient(timeout=60) as http:
            resp = await http.get(zip_url)
            resp.raise_for_status()

        try:
            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                # 优先 full.md，其次任意 .md
                for name in sorted(zf.namelist(), key=lambda n: (0 if "full.md" in n else 1)):
                    if name.endswith(".md"):
                        return zf.read(name).decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("mineru.zip_extract_failed", error=str(exc))

        return None

    # ── 便捷方法 (单条目 batch of 1) ─────────────────────────────────

    async def parse_url(
        self,
        source_url: str,
        *,
        data_id: str = "single",
        model_version: str | None = None,
    ) -> str | None:
        """单个 URL → markdown（内部用 URL batch of 1）。"""
        batch_id = await self.submit_url_batch(
            [{"url": source_url, "data_id": data_id}],
            model_version=model_version,
        )
        results = await self.poll_batch(batch_id, target_data_id=data_id)
        item = next((r for r in results if r.data_id == data_id), None)
        if item and item.state == "done" and item.zip_url:
            return await self.download_markdown(item.zip_url)
        if item:
            logger.warning("mineru.parse_url_failed", err=item.err_msg, url=source_url)
        return None

    async def parse_file(
        self,
        raw_bytes: bytes,
        *,
        file_name: str,
        data_id: str = "single",
        model_version: str | None = None,
    ) -> str | None:
        """单个文件 → markdown（内部用文件 batch of 1）。"""
        batch_id, upload_urls = await self.submit_file_batch(
            [{"name": file_name, "data_id": data_id}],
            model_version=model_version,
        )
        await self.upload_file(upload_urls[0], raw_bytes)
        results = await self.poll_batch(batch_id, target_data_id=data_id)
        item = next((r for r in results if r.data_id == data_id), None)
        if item and item.state == "done" and item.zip_url:
            return await self.download_markdown(item.zip_url)
        if item:
            logger.warning("mineru.parse_file_failed", err=item.err_msg, file=file_name)
        return None
