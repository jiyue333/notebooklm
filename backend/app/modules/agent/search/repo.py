"""Repository layer for SearchSession / SearchResult persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.agent.search.models import SearchResult, SearchSession


# ── sanitisation helpers ───────────────────────────────────────────────────

def _sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\x00", "")


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {
            (_sanitize_text(k) if isinstance(k, str) else k): _sanitize_json(v)
            for k, v in value.items()
        }
    return value


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _normalize_canonical_url(url: str | None) -> str:
    normalized = (url or "").strip().lower()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


# ── SearchSession CRUD ─────────────────────────────────────────────────────

_MODE_LABELS = {
    "fast": "Fast Research",
    "auto": "Auto Research",
    "deep": "Deep Research",
    "agent": "Agent Research",
}


async def create_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query: str,
    mode: str,
    execution_mode: str,
    provider_request_json: dict,
    provider_name: str = "agent",
    now: datetime | None = None,
) -> SearchSession:
    ts = now or datetime.now(UTC)
    search_session = SearchSession(
        user_id=user_id,
        notebook_id=notebook_id,
        query=query,
        normalized_query=query.strip().lower(),
        mode=mode,
        execution_mode=execution_mode,
        provider_name=provider_name,
        provider_request_json=provider_request_json,
        status="running" if execution_mode == "sync" else "queued",
        mode_label=_MODE_LABELS.get(mode, "Research"),
        result_count=0,
        created_at=ts,
        expires_at=ts + timedelta(days=1),
    )
    session.add(search_session)
    await session.flush()
    return search_session


async def get_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    search_session_id: str,
) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession).where(
            SearchSession.id == search_session_id,
            SearchSession.user_id == user_id,
            SearchSession.notebook_id == notebook_id,
        )
    )
    return result.scalar_one_or_none()


async def get_search_session_by_id(
    session: AsyncSession,
    *,
    search_session_id: str,
) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession).where(SearchSession.id == search_session_id)
    )
    return result.scalar_one_or_none()


async def find_reusable_search_session(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
    query_signature: str,
) -> SearchSession | None:
    result = await session.execute(
        select(SearchSession)
        .where(
            SearchSession.user_id == user_id,
            SearchSession.notebook_id == notebook_id,
            SearchSession.status.in_(["queued", "running", "completed"]),
        )
        .order_by(SearchSession.created_at.desc())
        .limit(20),
    )
    now = datetime.now(UTC)
    for row in result.scalars().all():
        if row.expires_at and row.expires_at <= now:
            continue
        request_json = row.provider_request_json or {}
        if str(request_json.get("querySignature") or "") == query_signature:
            return row
    return None


async def count_active_sessions(
    session: AsyncSession,
    *,
    user_id: str,
    notebook_id: str,
) -> int:
    result = await session.execute(
        select(SearchSession.id)
        .where(
            SearchSession.user_id == user_id,
            SearchSession.notebook_id == notebook_id,
            SearchSession.status.in_(["queued", "running"]),
        )
        .limit(10)
    )
    return len(result.scalars().all())


async def list_pending_sessions_for_sweep(
    session: AsyncSession,
    *,
    limit: int = 200,
) -> list[SearchSession]:
    result = await session.execute(
        select(SearchSession)
        .where(SearchSession.status.in_(["queued", "running"]))
        .order_by(SearchSession.created_at.asc())
        .limit(max(1, min(limit, 500)))
    )
    return list(result.scalars().all())


async def update_session_status(
    session: AsyncSession,
    *,
    search_session: SearchSession,
    status: str,
    result_count: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    completed_at: datetime | None = None,
) -> SearchSession:
    search_session.status = status
    if result_count is not None:
        search_session.result_count = result_count
    search_session.error_code = error_code
    search_session.error_message = error_message
    if completed_at is not None:
        search_session.completed_at = completed_at
    await session.flush()
    return search_session


# ── SearchResult CRUD ──────────────────────────────────────────────────────

async def save_agent_search_results(
    session: AsyncSession,
    *,
    search_session_id: str,
    cards: list[dict],
    created_at: datetime | None = None,
) -> list[str]:
    """Persist agent search result dicts as SearchResult rows.

    Returns list of created row IDs.
    """
    ts = created_at or datetime.now(UTC)
    await session.execute(
        delete(SearchResult).where(SearchResult.search_session_id == search_session_id)
    )
    rows: list[SearchResult] = []
    for card in cards:
        url = card.get("url", "")
        canonical_url = _normalize_canonical_url(url)
        url_hash = sha256(canonical_url.encode()).hexdigest() if canonical_url else ""
        sr = SearchResult(
            search_session_id=search_session_id,
            provider_result_id=None,
            raw_url=url,
            canonical_url=canonical_url or url,
            url_hash=url_hash,
            title=_sanitize_text(card.get("title", "")) or "Untitled",
            description=_sanitize_text(card.get("description")),
            author=_sanitize_text(card.get("author")),
            published_at=_coerce_datetime(card.get("publishedAt") or card.get("published_at")),
            domain=card.get("sourceName") or card.get("source_name") or card.get("domain", ""),
            favicon_url=card.get("faviconUrl") or card.get("favicon_url"),
            display_rank=card.get("displayRank") or card.get("display_rank", 0),
            raw_payload_json=_sanitize_json({
                "source_type_badge": card.get("sourceTypeBadge") or card.get("source_type_badge", ""),
                "authority_badge": card.get("authorityBadge") or card.get("authority_badge"),
                "why_selected": card.get("whySelected") or card.get("why_selected", ""),
                "highlights": card.get("highlights", []),
                "import_suggestion": card.get("importSuggestion") or card.get("import_suggestion", "optional"),
                "final_score": card.get("finalScore") or card.get("final_score", 0),
                "score_breakdown": card.get("scoreBreakdown") or card.get("score_breakdown", {}),
                "provider": card.get("provider"),
                "query_family": card.get("queryFamily") or card.get("query_family"),
                "preferred_site_hit": card.get("preferredSiteHit") or card.get("preferred_site_hit", False),
                "matched_preferred_site": card.get("matchedPreferredSite") or card.get("matched_preferred_site"),
                "duplicate_risk": card.get("duplicateRisk") or card.get("duplicate_risk", False),
                "selected_reason_tags": card.get("selectedReasonTags") or card.get("selected_reason_tags", []),
            }),
            created_at=ts,
        )
        rows.append(sr)
    if rows:
        session.add_all(rows)
        await session.flush()
    return [row.id for row in rows]


async def list_search_results(
    session: AsyncSession,
    *,
    search_session_id: str,
) -> list[SearchResult]:
    result = await session.execute(
        select(SearchResult)
        .where(SearchResult.search_session_id == search_session_id)
        .order_by(SearchResult.display_rank.asc(), desc(SearchResult.created_at))
    )
    return list(result.scalars().all())
