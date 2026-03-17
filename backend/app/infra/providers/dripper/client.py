"""Dripper / MinerU-HTML client – HTML main content extraction.

Priority: local Dripper Python API → lite LLM (LITE_LLM_*) → None.
The *caller* (html_parser) handles trafilatura fallback when all fail.
"""

from __future__ import annotations

import re

import structlog

from app.core.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_HTML_EXTRACT_SYSTEM_PROMPT = (
    "You are an expert HTML content extractor. "
    "Given raw HTML of a web page, extract ONLY the main article content. "
    "Ignore navigation, ads, sidebars, footers, and boilerplate. "
    "Output clean Markdown. Preserve headings, lists, tables, code blocks, "
    "and images (as ![alt](src)). Do NOT wrap the output in a code fence."
)

_HTML_EXTRACT_MAX_CHARS = 100_000


class DripperClient:
    """Stateless facade over Dripper local Python API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def extract(
        self,
        url: str,
        html: str | None = None,
    ) -> DripperResult | None:
        """Extract main content using local Dripper, then lite LLM fallback."""

        if not html:
            return None

        result = await self._extract_with_local(html)
        if result:
            return result

        return await self._extract_with_lite_llm(url, html)

    async def _extract_with_local(self, html: str) -> DripperResult | None:
        try:
            from dripper.api import Dripper  # type: ignore[import-untyped]
        except ImportError:
            return None

        try:
            dripper = Dripper(config={
                "use_fall_back": True,
                "raise_errors": False,
            })
            results = dripper.process(html)
            if not results or not results[0].main_html:
                return None

            markdown = _html_to_markdown(results[0].main_html)
            if not markdown:
                return None

            return DripperResult(
                markdown=markdown,
                title=_extract_title(markdown),
                source="dripper_local",
            )
        except Exception as exc:
            logger.warning("dripper.local_error", error=str(exc))
            return None

    async def _extract_with_lite_llm(
        self,
        url: str,
        html: str,
    ) -> DripperResult | None:
        """Fallback: use lite LLM (LITE_LLM_*) to extract main content."""
        from app.infra.ai.lite_models import build_lite_llm

        llm = build_lite_llm(self._settings)
        if not llm:
            return None

        truncated = html[:_HTML_EXTRACT_MAX_CHARS]
        user_msg = f"URL: {url}\n\n```html\n{truncated}\n```"

        try:
            response = await llm.ainvoke([
                {"role": "system", "content": _HTML_EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ])
            content = response.content.strip() if hasattr(response, "content") else str(response)
            markdown = _strip_code_fence(content).strip()
            if not markdown:
                return None

            return DripperResult(
                markdown=markdown,
                title=_extract_title(markdown),
                source="lite_llm",
            )
        except Exception as exc:
            logger.warning("dripper.lite_llm_error", url=url, error=str(exc))
            return None


class DripperResult:
    __slots__ = ("markdown", "title", "source")

    def __init__(self, markdown: str, title: str | None, source: str) -> None:
        self.markdown = markdown
        self.title = title
        self.source = source


# ── helpers ────────────────────────────────────────────────────────────

def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _html_to_markdown(html: str) -> str | None:
    try:
        import html2text  # type: ignore[import-untyped]

        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0
        result = h.handle(html).strip()
        return result if result else None
    except ImportError:
        pass

    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<p[^>]*>", "\n\n", text)
    text = re.sub(r"</p>", "", text)
    text = re.sub(
        r"<h([1-6])[^>]*>(.*?)</h\1>",
        lambda m: f"{'#' * int(m.group(1))} {m.group(2)}",
        text,
    )
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def _extract_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            return stripped[2:].strip()
    return None
