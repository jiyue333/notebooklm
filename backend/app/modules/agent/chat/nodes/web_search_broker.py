"""Node 4: Web Search Broker — 联网判定 + 搜索执行。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.cache import chat_web_search_key, get_json, set_json
from app.infra.telemetry.metrics import observe_chat_error, observe_chat_stage, observe_chat_web_search
from app.modules.agent.chat.state import ChatGraphState
from app.modules.settings.runtime import resolve_search_api_key, resolve_tavily_api_key

logger = structlog.get_logger(__name__)

_FRESHNESS_KEYWORDS = re.compile(
    r"(最新|现在|近期|最近|近两月|近两个月|动态|新闻|本周|本月|趋势|价格|版本|发布|官网|政策|"
    r"latest|current|recent|now|trend|price|release|update|official|news|breaking|this week|this month)",
    re.IGNORECASE,
)
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
_TAVILY_DISABLE_UNTIL_MONO = 0.0
_TAVILY_FAILURE_STREAK = 0
_TAVILY_COOLDOWN_SECONDS = 300


async def web_search_broker_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    settings = get_settings()
    query = state["query"]
    route = state.get("route", "general")
    tools_needed = state.get("tools_needed", [])
    router_need_web = bool(state.get("router_need_web_search", False))
    router_reason = str(state.get("router_web_search_reason", "") or "").strip().lower()
    user = state.get("user")
    user_id = str(state.get("user_id") or "")

    # ========== Router 决定是否联网 ==========
    need = router_need_web or ("web_search" in tools_needed)
    reason = _normalize_router_reason(router_reason) if router_reason else ("router_required" if need else "not_needed")

    # 兼容旧状态：若 router 未显式给出，但 query 明显是时效类，保守触发联网。
    if not need and not router_reason and _FRESHNESS_KEYWORDS.search(query):
        need, reason = True, "freshness"

    observe_chat_web_search(route=route, reason=reason)

    if not need:
        observe_chat_stage(stage="web_search_broker", route=route, status="skip", duration_ms=_ms(t0))
        return {
            "need_web_search": False,
            "web_search_reason": reason,
            "web_evidence": [],
        }

    # ========== 缓存命中 ==========
    cache_key = chat_web_search_key(user_id=user_id, route=route, query=query)
    t_cache = perf_counter()
    cached = await get_json(cache_key)
    logger.debug("chat.web_broker_cache_check", duration_ms=_ms(t_cache), hit=isinstance(cached, dict))
    if isinstance(cached, dict):
        cached_results = cached.get("results")
        if isinstance(cached_results, list):
            logger.info("chat.web_broker_cache_hit", duration_ms=_ms(t0), result_count=len(cached_results))
            observe_chat_stage(stage="web_search_broker", route=route, status="cache_hit", duration_ms=_ms(t0))
            return {
                "need_web_search": True,
                "web_search_reason": "cache_hit",
                "web_evidence": cached_results,
            }

    # ========== 搜索执行 ==========
    t_search = perf_counter()
    try:
        web_results = await _execute_search(query, user)
        logger.info("chat.web_broker_search_done", duration_ms=_ms(t_search), result_count=len(web_results))
    except Exception as exc:
        logger.warning("chat.web_search_execute_failed", duration_ms=_ms(t_search), error=str(exc)[:200])
        observe_chat_error(node="web_search_broker")
        observe_chat_stage(stage="web_search_broker", route=route, status="error", duration_ms=_ms(t0))
        return {"need_web_search": True, "web_search_reason": reason, "web_evidence": []}

    if web_results:
        await set_json(
            cache_key,
            {"results": web_results, "reason": reason},
            ttl_seconds=max(int(settings.chat_web_search_cache_ttl_seconds), 30),
        )

    observe_chat_stage(stage="web_search_broker", route=route, status="ok", duration_ms=_ms(t0))
    logger.info("chat.web_search", reason=reason, result_count=len(web_results))

    return {
        "need_web_search": True,
        "web_search_reason": reason,
        "web_evidence": web_results,
    }


async def _execute_search(query: str, user=None) -> list[dict]:
    """优先 Tavily → fallback Exa。"""

    settings = get_settings()
    exa_key, _ = resolve_search_api_key(user, settings) if user else (settings.exa_default_api_key, "default")
    tavily_key, _ = resolve_tavily_api_key(user, settings)

    # 尝试 Tavily
    if tavily_key and _tavily_is_available():
        client = None
        try:
            from app.infra.providers.tavily.search_client import TavilySearchClient, TavilySearchRequest

            client = TavilySearchClient()
            t_tavily = perf_counter()
            resp = await client.search(
                TavilySearchRequest(
                    query=query,
                    search_depth="basic",
                    max_results=5,
                    chunks_per_source=2,
                    timeout_seconds=6.0,
                ),
                api_key=tavily_key,
            )
            results = _parse_tavily_results(resp)
            logger.info("chat.tavily_search_done", duration_ms=_ms(t_tavily), result_count=len(results))
            _mark_tavily_success()
            return results
        except Exception as exc:
            disable_reason = _classify_tavily_failure(exc)
            _mark_tavily_failure(disable_reason)
            logger.warning(
                "chat.tavily_search_failed",
                duration_ms=_ms(t_tavily) if "t_tavily" in dir() else 0,
                error=str(exc)[:200],
                disable_tavily=bool(disable_reason),
                disable_reason=disable_reason or "",
            )
            if disable_reason and exa_key:
                return await _search_with_exa(query, exa_key)
        finally:
            if client is not None:
                await client.close()

    # 尝试 Exa
    if exa_key:
        return await _search_with_exa(query, exa_key)

    return []


async def _search_with_exa(query: str, exa_key: str) -> list[dict]:
    client = None
    t_exa = perf_counter()
    try:
        from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest

        client = ExaSearchClient()
        resp = await client.search(
            ExaSearchRequest(query=query, max_results=5, timeout_seconds=6.0),
            api_key=exa_key,
        )
        results = _parse_exa_results(resp)
        logger.info("chat.exa_search_done", duration_ms=_ms(t_exa), result_count=len(results))
        return results
    except Exception as exc:
        logger.warning("chat.exa_search_failed", duration_ms=_ms(t_exa), error=str(exc)[:200])
        return []
    finally:
        if client is not None:
            await client.close()


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


def _tavily_is_available() -> bool:
    global _TAVILY_DISABLE_UNTIL_MONO
    if _TAVILY_DISABLE_UNTIL_MONO <= 0:
        return True
    return perf_counter() >= _TAVILY_DISABLE_UNTIL_MONO


def _mark_tavily_success() -> None:
    global _TAVILY_FAILURE_STREAK, _TAVILY_DISABLE_UNTIL_MONO
    _TAVILY_FAILURE_STREAK = 0
    _TAVILY_DISABLE_UNTIL_MONO = 0.0


def _mark_tavily_failure(reason: str) -> None:
    global _TAVILY_FAILURE_STREAK, _TAVILY_DISABLE_UNTIL_MONO
    _TAVILY_FAILURE_STREAK += 1
    if reason in {"quota_exhausted", "auth_failed", "rate_limited"} or _TAVILY_FAILURE_STREAK >= 3:
        _TAVILY_DISABLE_UNTIL_MONO = perf_counter() + _TAVILY_COOLDOWN_SECONDS


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
        message = str(current).strip()
        if message:
            parts.append(message)
        response = getattr(current, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            if status_code is not None:
                parts.append(f"status={status_code}")
            response_text = str(getattr(response, "text", "")).strip()
            if response_text:
                parts.append(response_text[:240])
        current = current.__cause__ or current.__context__
        depth += 1
    return " | ".join(parts).lower()


def _normalize_router_reason(reason: str) -> str:
    value = (reason or "").strip().lower()
    if not value:
        return "router_required"
    allowed = {
        "router_llm",
        "router_freshness",
        "router_route_policy",
        "router_general_freshness",
        "router_required",
        "freshness",
        "not_needed",
        "cache_hit",
    }
    if value in allowed:
        return value
    return "router_llm"


def _parse_tavily_results(resp: dict) -> list[dict]:
    results: list[dict] = []
    for r in resp.get("results", [])[:5]:
        results.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": r.get("content", "")[:500],
            "source": "tavily",
            "published_date": r.get("published_date"),
        })
    return results


def _parse_exa_results(resp: dict) -> list[dict]:
    results: list[dict] = []
    for r in resp.get("results", [])[:5]:
        highlights = r.get("highlights", [])
        snippet = highlights[0] if highlights else r.get("text", "")[:500]
        results.append({
            "url": r.get("url", ""),
            "title": r.get("title", ""),
            "snippet": snippet[:500] if isinstance(snippet, str) else "",
            "source": "exa",
            "published_date": r.get("publishedDate"),
        })
    return results


def _ms(start: float) -> float:
    return round((perf_counter() - start) * 1000, 2)
