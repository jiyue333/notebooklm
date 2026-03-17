"""MinerU client – PDF/document → Markdown conversion.

Uses local MinerU Python API only (``mineru`` package).
Falls back to CLI if Python API fails.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_MINERU_TIMEOUT_SECONDS = 300


class MinerUClient:
    """Stateless facade over MinerU CLI / Python API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    @property
    def backend(self) -> str:
        return self._settings.mineru_backend

    async def parse(
        self,
        raw_bytes: bytes,
        *,
        file_ext: str,
    ) -> str | None:
        """Convert a document to markdown.  Returns ``None`` on failure."""

        suffix = file_ext if file_ext.startswith(".") else f".{file_ext}"

        with tempfile.TemporaryDirectory(prefix="mineru_") as tmp_dir:
            input_path = Path(tmp_dir) / f"input{suffix}"
            output_dir = Path(tmp_dir) / "output"
            input_path.write_bytes(raw_bytes)

            result = await self._run_python_api(input_path, output_dir)
            if result:
                return result

            return await self._run_cli(input_path, output_dir)

    # ── CLI ────────────────────────────────────────────────────────────

    async def _run_cli(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> str | None:
        if not shutil.which("mineru"):
            return None

        cmd = ["mineru", "-p", str(input_path), "-o", str(output_dir)]
        backend = self.backend
        if backend != "auto":
            cmd.extend(["-b", backend])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_MINERU_TIMEOUT_SECONDS,
            )
            if proc.returncode != 0:
                logger.warning(
                    "mineru.cli_error",
                    returncode=proc.returncode,
                    stderr=stderr.decode("utf-8", errors="replace")[:500],
                )
                return None
            return _collect_markdown(output_dir)
        except asyncio.TimeoutError:
            logger.warning("mineru.cli_timeout")
            return None
        except Exception as exc:
            logger.warning("mineru.cli_error", error=str(exc))
            return None

    # ── Python API ─────────────────────────────────────────────────────

    async def _run_python_api(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> str | None:
        try:
            from mineru import MinerUPipeline  # type: ignore[import-untyped]
        except ImportError:
            logger.warning("mineru.not_installed")
            return None

        backend = self.backend
        try:
            pipeline = MinerUPipeline(backend=backend if backend != "auto" else None)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: pipeline.run(str(input_path), str(output_dir)),
            )
            return _collect_markdown(output_dir)
        except Exception as exc:
            logger.warning("mineru.python_api_error", error=str(exc))
            return None

# ── helpers (module-private) ──────────────────────────────────────────

def _collect_markdown(output_dir: Path) -> str | None:
    md_files = sorted(output_dir.rglob("*.md"))
    if not md_files:
        json_files = sorted(output_dir.rglob("*.json"))
        if json_files:
            return _markdown_from_json(json_files[0])
        return None

    parts: list[str] = []
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8", errors="replace").strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts) if parts else None


def _markdown_from_json(json_path: Path) -> str | None:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            parts = [item.get("text", "") for item in data if item.get("text")]
            return "\n\n".join(parts) if parts else None
        if isinstance(data, dict) and "markdown" in data:
            return data["markdown"]
    except Exception:
        pass
    return None
