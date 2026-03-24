"""Node 4: Web Search Broker — 联网判定 + 搜索执行。"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.telemetry.metrics import observe_chat_error, observe_chat_stage, observe_chat_web_search
from app.modules.agent.chat.state import ChatGraphState

logger = structlog.get_logger(__name__)

_FRESHNESS_KEYWORDS = re.compile(
    r"(最新|现在|近期|趋势|价格|版本|发布|官网|政策|"
    r"latest|current|recent|now|trend|price|release|update|official)",
    re.IGNORECASE,
)


async def web_search_broker_node(state: ChatGraphState) -> dict[str, Any]:
    t0 = perf_counter()
    query = state["query"]
    route = state.get("route", "general")
    local_evidence = state.get("local_evidence", [])
    tools_needed = state.get("tools_needed", [])

    # ========== 规则层快速判定 ==========
    need = False
    reason = "not_needed"

    if "web_search" in tools_needed:
        need, reason = True, "user_explicit"
    elif _FRESHNESS_KEYWORDS.search(query):
        need, reason = True, "freshness"
    elif not local_evidence and route != "general":
        need, reason = True, "insufficient_local"

    if not need:
        settings = get_settings()
        if local_evidence:
            max_score = max(e.get("score", 0) for e in local_evidence)
            if max_score < settings.chat_web_search_score_threshold and route != "general":
                need, reason = True, "insufficient_local"

    observe_chat_web_search(route=route, reason=reason)

    if not need:
        observe_chat_stage(stage="web_search_broker", route=route, status="skip", duration_ms=_ms(t0))
        return {
            "need_web_search": False,
            "web_search_reason": reason,
            "web_evidence": [],
        }

    # ========== 搜索执行 ==========
    try:
        web_results = await _execute_search(query)
    except Exception as exc:
        logger.warning("chat.web_search_execute_failed", error=str(exc)[:200])
        observe_chat_error(node="web_search_broker")
        observe_chat_stage(stage="web_search_broker", route=route, status="error", duration_ms=_ms(t0))
        return {"need_web_search": True, "web_search_reason": reason, "web_evidence": []}

    observe_chat_stage(stage="web_search_broker", route=route, status="ok", duration_ms=_ms(t0))
    logger.info("chat.web_search", reason=reason, result_count=len(web_results))

    return {
        "need_web_search": True,
        "web_search_reason": reason,
        "web_evidence": web_results,
    }


async def _execute_search(query: str) -> list[dict]:
    """优先 Tavily → fallback Exa。"""

    settings = get_settings()

    # 尝试 Tavily
    tavily_key = settings.tavily_default_api_key
    if tavily_key:
        try:
            from app.infra.providers.tavily.search_client import TavilySearchClient, TavilySearchRequest

            client = TavilySearchClient()
            resp = await client.search(
                TavilySearchRequest(
                    query=query,
                    search_depth="basic",
                    max_results=5,
                    chunks_per_source=2,
                ),
                api_key=tavily_key,
            )
            await client.close()
            return _parse_tavily_results(resp)
        except Exception as exc:
            logger.warning("chat.tavily_search_failed", error=str(exc)[:200])

    # 尝试 Exa
    exa_key = settings.exa_default_api_key
    if exa_key:
        try:
            from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest

            client = ExaSearchClient()
            resp = await client.search(
                ExaSearchRequest(query=query, max_results=5),
                api_key=exa_key,
            )
            await client.close()
            return _parse_exa_results(resp)
        except Exception as exc:
            logger.warning("chat.exa_search_failed", error=str(exc)[:200])

    return []


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
