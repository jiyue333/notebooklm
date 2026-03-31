"""Tavily 提供商熔断器：故障检测、短暂禁用与错误分类。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.modules.agent.search.utils import _safe_text

_TAVILY_DISABLE_KEYWORDS = (
    "quota",
    "credit",
    "credits",
    "insufficient",
    "usage limit",
    "payment required",
    "rate limit",
    "too many requests",
    "429",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "auth",
)
_TAVILY_DISABLE_SECONDS_BY_REASON = {
    "quota_exhausted": 1800,
    "auth_failed": 1800,
    "rate_limited": 300,
}
_TAVILY_PROVIDER_ERROR_STREAK_THRESHOLD = 3
_TAVILY_PROVIDER_ERROR_DISABLE_SECONDS = 180
_TAVILY_CIRCUIT: dict[str, Any] = {
    "disabled_until": None,
    "reason": "",
    "failure_streak": 0,
}


def _get_tavily_circuit_state() -> tuple[bool, str]:
    now = datetime.now(UTC)
    disabled_until = _TAVILY_CIRCUIT.get("disabled_until")
    reason = _safe_text(_TAVILY_CIRCUIT.get("reason"))
    if isinstance(disabled_until, datetime):
        if disabled_until > now:
            return True, reason or "provider_disabled"
        _TAVILY_CIRCUIT["disabled_until"] = None
        _TAVILY_CIRCUIT["reason"] = ""
    return False, ""


def _record_tavily_success() -> None:
    _TAVILY_CIRCUIT["failure_streak"] = 0


def _record_tavily_failure(reason: str) -> bool:
    reason = _safe_text(reason) or "provider_error"
    streak = int(_TAVILY_CIRCUIT.get("failure_streak") or 0) + 1
    _TAVILY_CIRCUIT["failure_streak"] = streak

    disable_seconds = int(_TAVILY_DISABLE_SECONDS_BY_REASON.get(reason, 0))
    if reason == "provider_error" and streak >= _TAVILY_PROVIDER_ERROR_STREAK_THRESHOLD:
        disable_seconds = _TAVILY_PROVIDER_ERROR_DISABLE_SECONDS
    if disable_seconds <= 0:
        return False

    _TAVILY_CIRCUIT["disabled_until"] = datetime.now(UTC) + timedelta(seconds=disable_seconds)
    _TAVILY_CIRCUIT["reason"] = reason
    return True


def _error_chain_text(exc: Exception, *, max_depth: int = 4) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    visited: set[int] = set()
    depth = 0
    while current is not None and depth < max_depth:
        marker = id(current)
        if marker in visited:
            break
        visited.add(marker)
        message = _safe_text(current)
        if message:
            parts.append(message)
        response = getattr(current, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                parts.append(f"status={status_code}")
            response_text = _safe_text(getattr(response, "text", ""))
            if response_text:
                parts.append(response_text[:240])
        current = current.__cause__ or current.__context__
        depth += 1
    return " | ".join(parts).lower()


def _classify_tavily_failure(exc: Exception) -> str:
    text = _error_chain_text(exc)
    if not text:
        return "provider_error"
    if any(keyword in text for keyword in _TAVILY_DISABLE_KEYWORDS):
        if any(keyword in text for keyword in ("quota", "credit", "insufficient", "usage limit", "payment required")):
            return "quota_exhausted"
        if any(keyword in text for keyword in ("unauthorized", "forbidden", "invalid api key", "auth")):
            return "auth_failed"
        return "rate_limited"
    return "provider_error"
