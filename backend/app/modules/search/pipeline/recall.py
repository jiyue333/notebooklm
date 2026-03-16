"""Stage C – Multi-Source Recall.

Runs a provider router across web + scholarly routes and, in deep mode,
performs a second-pass seed expansion so deep search is materially
different from fast/auto.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from urllib.parse import urlparse, urlunparse

import httpx
import structlog

from app.infra.providers.exa.search_client import (
    ExaSearchClient,
    ExaSearchMode,
    ExaSearchRequest,
)
from app.modules.search.pipeline.types import QueryFamily, QueryRole, RawCandidate, SourceMix

logger = structlog.get_logger(__name__)

_VALID_EXA_MODES: set[str] = {"fast", "auto", "deep"}
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", re.IGNORECASE)
_ACADEMIC_ROLES = {
    QueryRole.PRIMARY,
    QueryRole.TERMINOLOGY,
    QueryRole.CRITICAL,
    QueryRole.IMPLEMENTATION,
}


async def recall(
    families: list[QueryFamily],
    *,
    exa_api_key: str,
    search_mode: str,
    expected_source_mix: list[SourceMix] | None = None,
) -> list[RawCandidate]:
    """Execute all recall routes and return a flat list of raw candidates."""

    source_mix = set(expected_source_mix or [])
    exa_client = ExaSearchClient()
    academic_client = httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={
            "User-Agent": "notebooklm-search/1.0 (mailto:notebooklm@example.com)",
        },
    )
    try:
        candidates: list[RawCandidate] = []
        batch_size = 3
        for batch_start in range(0, len(families), batch_size):
            batch = families[batch_start : batch_start + batch_size]
            tasks = [
                _search_one_family(
                    exa_client,
                    academic_client,
                    family,
                    exa_api_key=exa_api_key,
                    search_mode=search_mode,
                    source_mix=source_mix,
                )
                for family in batch
            ]
            nested_results = await asyncio.gather(*tasks, return_exceptions=True)
            for family, result in zip(batch, nested_results):
                if isinstance(result, BaseException):
                    logger.warning(
                        "search.recall.family_failed",
                        role=family.role.value,
                        query=family.query_text[:80],
                        error=str(result),
                    )
                    continue
                candidates.extend(result)
            if batch_start + batch_size < len(families):
                await asyncio.sleep(0.5)

        if search_mode == "deep":
            candidates.extend(
                await _run_seed_expansion(
                    exa_client,
                    academic_client,
                    candidates,
                    exa_api_key=exa_api_key,
                    source_mix=source_mix,
                )
            )
        return candidates
    finally:
        await exa_client.close()
        await academic_client.aclose()


async def _search_one_family(
    exa_client: ExaSearchClient,
    academic_client: httpx.AsyncClient,
    family: QueryFamily,
    *,
    exa_api_key: str,
    search_mode: str,
    source_mix: set[SourceMix],
) -> list[RawCandidate]:
    exa_mode: ExaSearchMode = "auto"
    if search_mode in _VALID_EXA_MODES:
        exa_mode = search_mode  # type: ignore[assignment]

    tasks = [
        _search_exa_family(
            exa_client,
            family,
            exa_api_key=exa_api_key,
            exa_mode=exa_mode,
        ),
    ]
    if _should_use_academic_route(family, source_mix, search_mode):
        tasks.extend([
            _search_crossref_family(academic_client, family),
            _search_arxiv_family(academic_client, family),
        ])

    results = await asyncio.gather(*tasks, return_exceptions=True)
    candidates: list[RawCandidate] = []
    for result in results:
        if isinstance(result, BaseException):
            logger.warning(
                "search.recall.provider_failed",
                role=family.role.value,
                query=family.query_text[:80],
                error=str(result),
            )
            continue
        candidates.extend(result)
    return candidates


async def _run_seed_expansion(
    exa_client: ExaSearchClient,
    academic_client: httpx.AsyncClient,
    candidates: list[RawCandidate],
    *,
    exa_api_key: str,
    source_mix: set[SourceMix],
) -> list[RawCandidate]:
    seeds = _pick_seed_titles(candidates)
    if not seeds:
        return []

    tasks = []
    for title in seeds:
        seed_query = f"\"{title}\" related work benchmark case study"
        family = QueryFamily(
            role=QueryRole.PRIMARY,
            query_text=seed_query,
            max_results=4,
        )
        tasks.append(_search_exa_family(
            exa_client,
            family,
            exa_api_key=exa_api_key,
            exa_mode="deep",
            provider="exa_seed",
            rank_offset=50,
        ))
        if SourceMix.PAPER in source_mix:
            tasks.extend([
                _search_crossref_family(academic_client, family, provider="crossref_seed", rank_offset=50),
                _search_arxiv_family(academic_client, family, provider="arxiv_seed", rank_offset=50),
            ])

    nested = await asyncio.gather(*tasks, return_exceptions=True)
    expanded: list[RawCandidate] = []
    for result in nested:
        if isinstance(result, BaseException):
            logger.warning("search.recall.seed_expansion_failed", error=str(result))
            continue
        expanded.extend(result)
    return expanded


def _pick_seed_titles(candidates: list[RawCandidate]) -> list[str]:
    seen: set[str] = set()
    seeds: list[str] = []
    sorted_candidates = sorted(
        candidates,
        key=lambda item: (
            0 if item.query_role == QueryRole.PRIMARY else 1,
            item.display_rank,
        ),
    )
    for candidate in sorted_candidates:
        title = (candidate.title or "").strip()
        if len(title) < 18:
            continue
        normalized = title.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        seeds.append(title)
        if len(seeds) >= 3:
            break
    return seeds


def _should_use_academic_route(
    family: QueryFamily,
    source_mix: set[SourceMix],
    search_mode: str,
) -> bool:
    if SourceMix.PAPER in source_mix:
        return True
    if family.role in _ACADEMIC_ROLES:
        return True
    return search_mode == "deep"


async def _search_exa_family(
    client: ExaSearchClient,
    family: QueryFamily,
    *,
    exa_api_key: str,
    exa_mode: ExaSearchMode,
    provider: str = "exa",
    rank_offset: int = 0,
) -> list[RawCandidate]:
    request = ExaSearchRequest(
        query=family.query_text,
        mode=exa_mode,
        max_results=family.max_results,
        freshness_hours=family.freshness_hours,
    )
    payload = await client.search(request, api_key=exa_api_key)
    return _map_exa_results(payload, query_role=family.role, provider=provider, rank_offset=rank_offset)


async def _search_crossref_family(
    client: httpx.AsyncClient,
    family: QueryFamily,
    *,
    provider: str = "crossref",
    rank_offset: int = 0,
) -> list[RawCandidate]:
    response = await client.get(
        "https://api.crossref.org/works",
        params={
            "query.bibliographic": family.query_text,
            "rows": min(family.max_results, 8),
            "sort": "relevance",
            "order": "desc",
        },
    )
    response.raise_for_status()
    items = (response.json().get("message") or {}).get("items") or []

    candidates: list[RawCandidate] = []
    for index, item in enumerate(items, start=1):
        doi = item.get("DOI")
        raw_url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
        canonical_url = _canonicalize_url(raw_url) if raw_url else ""
        title = " ".join(item.get("title") or []) or item.get("container-title", [""])[0] or "Untitled result"
        summary = _strip_tags(item.get("abstract") or "") or None
        authors = item.get("author") or []
        author = None
        if authors:
            first = authors[0]
            author = " ".join(part for part in [first.get("given"), first.get("family")] if part)
        candidates.append(
            RawCandidate(
                provider=provider,
                provider_result_id=doi,
                raw_url=raw_url,
                canonical_url=canonical_url,
                title=title,
                description=summary,
                author=author,
                published_at=_parse_crossref_datetime(item),
                domain=urlparse(canonical_url).netloc if canonical_url else "doi.org",
                preview_markdown=summary[:500] if summary else None,
                raw_payload=item,
                query_role=family.role,
                display_rank=index + rank_offset,
            )
        )
    return candidates


async def _search_arxiv_family(
    client: httpx.AsyncClient,
    family: QueryFamily,
    *,
    provider: str = "arxiv",
    rank_offset: int = 0,
) -> list[RawCandidate]:
    response = await client.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f"all:{family.query_text}",
            "start": 0,
            "max_results": min(family.max_results, 8),
        },
    )
    response.raise_for_status()
    root = ET.fromstring(response.text)
    candidates: list[RawCandidate] = []
    for index, entry in enumerate(root.findall("atom:entry", _ATOM_NS), start=1):
        abs_url = _entry_text(entry, "atom:id")
        raw_url = _arxiv_abs_to_pdf(abs_url) if abs_url else ""
        canonical_url = _canonicalize_url(raw_url) if raw_url else ""
        title = re.sub(r"\s+", " ", _entry_text(entry, "atom:title")).strip() or "Untitled result"
        summary = re.sub(r"\s+", " ", _entry_text(entry, "atom:summary")).strip() or None
        author = _entry_text(entry, "atom:author/atom:name")
        published = _parse_datetime(_entry_text(entry, "atom:published"))
        highlights = [summary[:220]] if summary else []
        candidates.append(
            RawCandidate(
                provider=provider,
                provider_result_id=abs_url or raw_url,
                raw_url=raw_url,
                canonical_url=canonical_url,
                title=title,
                description=summary,
                author=author or None,
                published_at=published,
                domain="arxiv.org",
                preview_markdown=summary[:500] if summary else None,
                highlights=highlights,
                raw_payload={"source": "arxiv", "entry_id": abs_url or raw_url},
                query_role=family.role,
                display_rank=index + rank_offset,
            )
        )
    return candidates


def _map_exa_results(
    payload: dict,
    *,
    query_role: QueryRole,
    provider: str,
    rank_offset: int = 0,
) -> list[RawCandidate]:
    raw_results = payload.get("results") or payload.get("data") or []
    candidates: list[RawCandidate] = []

    for index, result in enumerate(raw_results, start=1):
        raw_url = result.get("url") or ""
        canonical_url = _canonicalize_url(raw_url) if raw_url else ""
        domain = urlparse(canonical_url).netloc if canonical_url else None

        highlights = _extract_highlights(result)
        preview = _build_preview(result, highlights)

        candidates.append(
            RawCandidate(
                provider=provider,
                provider_result_id=result.get("id"),
                raw_url=raw_url,
                canonical_url=canonical_url,
                title=result.get("title") or domain or "Untitled result",
                description=result.get("summary") or result.get("description"),
                author=result.get("author"),
                published_at=_parse_datetime(result.get("publishedDate")),
                domain=domain,
                favicon_url=result.get("favicon"),
                preview_markdown=preview,
                highlights=highlights,
                raw_payload=result,
                query_role=query_role,
                display_rank=index + rank_offset,
            )
        )

    return candidates


def _extract_highlights(result: dict) -> list[str]:
    raw = result.get("highlights") or []
    if isinstance(raw, list):
        return [h.strip() for h in raw if isinstance(h, str) and h.strip()]
    return []


def _build_preview(result: dict, highlights: list[str]) -> str | None:
    if highlights:
        return "\n\n".join(f"> {snippet}" for snippet in highlights)
    summary = result.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    text = result.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()[:500]
    return None


def _arxiv_abs_to_pdf(url: str) -> str:
    """Convert arxiv abs page URL to PDF URL for direct paper import."""
    m = _ARXIV_ABS_RE.search(url)
    if m:
        return f"https://arxiv.org/pdf/{m.group(1)}.pdf"
    return url


def _canonicalize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    normalized_path = parsed.path.rstrip("/") or "/"
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        normalized_path,
        "",
        parsed.query,
        "",
    ))


def _entry_text(entry: ET.Element, selector: str) -> str:
    node = entry.find(selector, _ATOM_NS)
    return node.text.strip() if node is not None and node.text else ""


def _strip_tags(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", value).replace("\n", " ").strip()


def _parse_crossref_datetime(item: dict) -> datetime | None:
    for field in ("published-print", "published-online", "published", "issued", "created"):
        parts = ((item.get(field) or {}).get("date-parts") or [])
        if not parts:
            continue
        date_parts = parts[0]
        if not date_parts:
            continue
        year = int(date_parts[0])
        month = int(date_parts[1]) if len(date_parts) > 1 else 1
        day = int(date_parts[2]) if len(date_parts) > 2 else 1
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_datetime(value: str | None):
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed
    except ValueError:
        return None
