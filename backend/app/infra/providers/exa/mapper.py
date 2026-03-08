from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse, urlunparse

from app.modules.search.dto import SearchCandidateDTO


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _canonicalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    normalized_path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            normalized_path,
            "",
            parsed.query,
            "",
        )
    )


def _build_preview(result: dict) -> str | None:
    highlights = result.get("highlights") or []
    if isinstance(highlights, list) and highlights:
        return "\n\n".join(f"> {snippet.strip()}" for snippet in highlights if snippet)

    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()

    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()[:500]
    return None


class ExaResultMapper:
    @staticmethod
    def map_search_results(payload: dict) -> list[SearchCandidateDTO]:
        raw_results = payload.get("results") or payload.get("data") or []
        candidates: list[SearchCandidateDTO] = []

        for index, result in enumerate(raw_results, start=1):
            raw_url = result.get("url") or ""
            canonical_url = _canonicalize_url(raw_url) if raw_url else ""
            domain = urlparse(canonical_url).netloc if canonical_url else None
            candidates.append(
                SearchCandidateDTO(
                    provider_result_id=result.get("id"),
                    raw_url=raw_url,
                    canonical_url=canonical_url,
                    title=result.get("title") or domain or "Untitled result",
                    description=result.get("summary") or result.get("description"),
                    author=result.get("author"),
                    published_at=_parse_datetime(result.get("publishedDate")),
                    domain=domain,
                    favicon_url=result.get("favicon"),
                    display_rank=index,
                    preview_markdown=_build_preview(result),
                    raw_payload=result,
                )
            )

        return candidates
