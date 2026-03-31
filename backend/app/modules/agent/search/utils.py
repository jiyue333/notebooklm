"""搜索模块内部通用工具：文本处理、URL 规范化、时间解析、数学辅助。"""

from __future__ import annotations

import math
import os
import re
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from urllib.parse import urlparse


def _eval_force_serial_enabled() -> bool:
    value = str(os.getenv("EVAL_FORCE_SERIAL") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _elapsed_ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _safe_highlights(values: Any, *, limit: int = 3) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        text = _safe_text(value)
        if text:
            normalized.append(text)
    return normalized[:limit]


def _clamp(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", left))
    right_tokens = set(re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", right))
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens) or 1
    return intersection / union


def _domain_from_url(url: str) -> str:
    parsed = urlparse(_safe_text(url))
    return parsed.netloc.lower().removeprefix("www.")


def _normalize_domain_token(raw: str) -> str:
    token = _safe_text(raw).lower()
    if not token:
        return ""
    token = token.removeprefix("site:")
    if "://" in token:
        parsed = urlparse(token)
        token = parsed.netloc or token
    token = token.split("/")[0].strip().strip(".,;:!?)]}>'\"")
    token = token.removeprefix("www.")
    if "." not in token:
        return ""
    return token


def _extract_query_site_domains(query: str) -> list[str]:
    matches = re.findall(r"(?:^|\s)site:([^\s]+)", (query or "").lower())
    domains: list[str] = []
    for raw in matches:
        normalized = _normalize_domain_token(raw)
        if normalized:
            domains.append(normalized)
    return list(dict.fromkeys(domains))


def _normalize_url(url: str) -> str:
    normalized = _safe_text(url).lower()
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _blend_scores(primary: float, rule_score: float) -> float:
    return round(_clamp(primary * 0.7 + rule_score * 0.3), 4)


def _match_preferred_site(domain: str, preferred_sites: list[str]) -> str | None:
    lowered = domain.lower()
    for site in preferred_sites:
        if site and site in lowered:
            return site
    return None
