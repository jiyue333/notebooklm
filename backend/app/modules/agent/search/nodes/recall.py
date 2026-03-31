"""召回节点：多提供商并行检索、结果去重与合并。"""

from __future__ import annotations

import asyncio
import re
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import structlog

from app.infra.providers.exa.search_client import ExaSearchClient, ExaSearchRequest
from app.infra.providers.tavily.search_client import TavilySearchClient, TavilySearchRequest
from app.infra.telemetry.metrics import (
    observe_search_dedup,
    observe_search_partial_failure,
    observe_search_stage,
)
from app.infra.telemetry.tracing import start_span
from app.modules.agent.search.circuit_breaker import (
    _classify_tavily_failure,
    _get_tavily_circuit_state,
    _record_tavily_failure,
    _record_tavily_success,
)
from app.modules.agent.search.state import SearchCandidate, SearchGraphState, SearchQueryPlan, SearchTaskSpec
from app.modules.agent.search.utils import (
    _clamp,
    _domain_from_url,
    _elapsed_ms,
    _eval_force_serial_enabled,
    _normalize_url,
    _parse_datetime,
    _safe_highlights,
    _safe_text,
    _token_similarity,
)

logger = structlog.get_logger(__name__)

_MAX_PROVIDER_CALLS_PER_SEARCH = 6


def make_recall_node():
    """返回召回 LangGraph 节点函数。"""

    async def recall_node(state: SearchGraphState) -> dict[str, Any]:
        t0 = perf_counter()
        mode = state["mode"]
        round_no = state["current_round"]
        with start_span("search.recall", attributes={"search.mode": mode, "search.round": round_no}):
            exa_plan, tavily_plan = _plans_for_round(
                task_spec=state["task_spec"],
                round_no=round_no,
                existing_article_urls=state.get("existing_article_urls", []),
                recall_candidates=state.get("recall_candidates", []),
                forced_include_domains=state.get("forced_include_domains", []),
            )
            forced_domains = list(state.get("forced_include_domains") or [])
            provider_call_budget = int(state.get("provider_call_budget") or _MAX_PROVIDER_CALLS_PER_SEARCH)
            provider_calls_used = int(state.get("provider_calls_used") or 0)
            provider_call_counts = dict(state.get("provider_call_counts") or {"exa": 0, "tavily": 0})
            tavily_disabled = bool(state.get("tavily_disabled"))
            tavily_disable_reason = _safe_text(state.get("tavily_disable_reason"))
            debug_payload = dict(state.get("debug", {}))
            provider_attempts_total = int(debug_payload.get("providerAttempts") or 0)
            provider_failures_total = int(debug_payload.get("providerFailures") or 0)
            provider_all_failed_seen = bool(debug_payload.get("providerAllFailed"))
            tavily_globally_disabled, tavily_global_reason = _get_tavily_circuit_state()
            if tavily_globally_disabled:
                tavily_disabled = True
                if not tavily_disable_reason:
                    tavily_disable_reason = tavily_global_reason
            budget_left = max(provider_call_budget - provider_calls_used, 0)

            tasks: list[Any] = []
            task_provider_tags: list[str] = []
            is_first_round = round_no == 1
            if state.get("exa_api_key") and budget_left > 0:
                tasks.append(
                    _search_with_exa(
                        exa_api_key=state.get("exa_api_key"),
                        mode=mode,
                        task_spec=state["task_spec"],
                        query_plan=exa_plan,
                        include_domains=None if is_first_round else (forced_domains or None),
                        disable_excludes=is_first_round,
                        max_results=15 if is_first_round else 10,
                    ),
                )
                task_provider_tags.append("exa")
                provider_calls_used += 1
                provider_call_counts["exa"] = int(provider_call_counts.get("exa", 0)) + 1
                budget_left -= 1

            if state.get("tavily_api_key") and budget_left > 0 and not tavily_disabled:
                tasks.append(
                    _search_with_tavily(
                        tavily_api_key=state.get("tavily_api_key"),
                        mode=mode,
                        task_spec=state["task_spec"],
                        query_plan=tavily_plan,
                        include_domains=forced_domains or None,
                        disable_excludes=is_first_round,
                        max_results=5 if is_first_round else 10,
                    ),
                )
                task_provider_tags.append("tavily")
                provider_calls_used += 1
                provider_call_counts["tavily"] = int(provider_call_counts.get("tavily", 0)) + 1
                budget_left -= 1

            if not tasks:
                observe_search_stage(stage="recall", mode=mode, status="ok", duration_ms=_elapsed_ms(t0))
                return {
                    "provider_calls_used": provider_calls_used,
                    "provider_call_counts": provider_call_counts,
                    "tavily_disabled": tavily_disabled,
                    "tavily_disable_reason": tavily_disable_reason,
                    "recall_summary": {
                        "currentRound": round_no,
                        "candidateCount": len(state.get("recall_candidates", [])),
                        "selectedCount": len(state.get("selected_candidates", [])),
                        "providerCounts": provider_call_counts,
                        "providerCallsUsed": provider_calls_used,
                        "providerCallBudget": provider_call_budget,
                        "forcedIncludeDomains": forced_domains,
                        "queryPlans": {"exa": exa_plan.model_dump(), "tavily": tavily_plan.model_dump()},
                        "tavilyDisabled": tavily_disabled,
                        "tavilyDisableReason": tavily_disable_reason,
                    },
                    "debug": {
                        **debug_payload,
                        "providerAttempts": provider_attempts_total,
                        "providerFailures": provider_failures_total,
                        "providerAllFailed": provider_all_failed_seen,
                        "tavilyDisabled": tavily_disabled,
                        "tavilyDisableReason": tavily_disable_reason,
                    },
                }

            provider_t0s = {tag: perf_counter() for tag in task_provider_tags}
            if _eval_force_serial_enabled():
                results: list[Any] = []
                for idx, task in enumerate(tasks):
                    tag = task_provider_tags[idx]
                    provider_t0s[tag] = perf_counter()
                    try:
                        results.append(await task)
                    except Exception as exc:  # noqa: BLE001
                        results.append(exc)
            else:
                results = await asyncio.gather(*tasks, return_exceptions=True)

            new_candidates: list[SearchCandidate] = []
            failure_count = 0
            provider_attempts = len(task_provider_tags)
            tavily_disabled_next = tavily_disabled
            tavily_disable_reason_next = tavily_disable_reason
            for provider_tag, result in zip(task_provider_tags, results, strict=False):
                provider_ms = _elapsed_ms(provider_t0s.get(provider_tag, t0))
                if isinstance(result, list):
                    if provider_tag == "tavily":
                        _record_tavily_success()
                    logger.info(
                        "search.provider_done",
                        provider=provider_tag,
                        round=round_no,
                        duration_ms=provider_ms,
                        result_count=len(result),
                    )
                    for item in result:
                        new_candidates.append(item.model_copy(update={"recall_round": round_no}))
                elif isinstance(result, Exception):
                    failure_count += 1
                    logger.warning(
                        "search.recall_task_failed",
                        provider=provider_tag,
                        round=round_no,
                        duration_ms=provider_ms,
                        error=str(result)[:200],
                    )
                    if provider_tag == "tavily":
                        disable_reason = _classify_tavily_failure(result)
                        if disable_reason:
                            tavily_disabled_next = True
                            tavily_disable_reason_next = disable_reason
                            globally_disabled = _record_tavily_failure(disable_reason)
                            logger.warning(
                                "search.tavily_disabled_for_session",
                                reason=disable_reason,
                                globally_disabled=globally_disabled,
                                error=str(result)[:200],
                            )

            provider_all_failed = provider_attempts > 0 and failure_count >= provider_attempts
            provider_attempts_total += provider_attempts
            provider_failures_total += failure_count
            provider_all_failed_seen = provider_all_failed_seen or provider_all_failed

            if failure_count > 0 and new_candidates:
                observe_search_partial_failure(mode=mode)

            existing_count = len(state.get("recall_candidates", []))
            merged_candidates, seen_urls = _merge_candidates(
                existing=state.get("recall_candidates", []),
                seen_urls=set(state.get("seen_urls", [])),
                new_candidates=new_candidates,
            )
            dedup_count = len(new_candidates) - (len(merged_candidates) - existing_count)
            if dedup_count > 0:
                observe_search_dedup(mode=mode, dedup_type="url_canonicalize", count=dedup_count)

            recall_ms = _elapsed_ms(t0)
            logger.info(
                "search.recall_done",
                round=round_no,
                mode=mode,
                duration_ms=recall_ms,
                new_count=len(new_candidates),
                dedup_count=dedup_count,
                merged_total=len(merged_candidates),
                failures=failure_count,
                provider_all_failed=provider_all_failed,
            )
            observe_search_stage(stage="recall", mode=mode, status="ok", duration_ms=recall_ms)
            return {
                "recall_candidates": merged_candidates,
                "seen_urls": sorted(seen_urls),
                "provider_calls_used": provider_calls_used,
                "provider_call_counts": provider_call_counts,
                "tavily_disabled": tavily_disabled_next,
                "tavily_disable_reason": tavily_disable_reason_next,
                "recall_summary": {
                    "currentRound": round_no,
                    "candidateCount": len(merged_candidates),
                    "selectedCount": len(state.get("selected_candidates", [])),
                    "providerCounts": provider_call_counts,
                    "providerCallsUsed": provider_calls_used,
                    "providerCallBudget": provider_call_budget,
                    "forcedIncludeDomains": forced_domains,
                    "queryPlans": {"exa": exa_plan.model_dump(), "tavily": tavily_plan.model_dump()},
                    "providerAttempts": provider_attempts,
                    "providerFailures": failure_count,
                    "providerAllFailed": provider_all_failed,
                    "providerAttemptsTotal": provider_attempts_total,
                    "providerFailuresTotal": provider_failures_total,
                    "tavilyDisabled": tavily_disabled_next,
                    "tavilyDisableReason": tavily_disable_reason_next,
                },
                "debug": {
                    **debug_payload,
                    "providerAttempts": provider_attempts_total,
                    "providerFailures": provider_failures_total,
                    "providerAllFailed": provider_all_failed_seen,
                    "tavilyDisabled": tavily_disabled_next,
                    "tavilyDisableReason": tavily_disable_reason_next,
                },
            }

    return recall_node


# ---------------------------------------------------------------------------
# 查询计划
# ---------------------------------------------------------------------------

def _build_exclude_domains(existing_article_urls: list[str]) -> list[str]:
    domains: list[str] = []
    for url in existing_article_urls:
        domain = _domain_from_url(url)
        if domain:
            domains.append(domain)
    return list(dict.fromkeys(domains))


def _build_tavily_exclude_paths(existing_article_urls: list[str]) -> list[str]:
    paths: list[str] = []
    for url in existing_article_urls:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            continue
        if not parsed.path:
            continue
        normalized_path = parsed.path.rstrip("/") or "/"
        paths.append(rf"^{re.escape(normalized_path)}/?$")
    return list(dict.fromkeys(paths))


def _resolve_exa_max_age_hours(task_spec: SearchTaskSpec) -> int | None:
    if task_spec.time_sensitivity == "high":
        return 24 * 7
    if task_spec.time_sensitivity == "medium":
        return 24 * 30
    return None


def _resolve_tavily_time_range(task_spec: SearchTaskSpec) -> str | None:
    if task_spec.time_sensitivity == "high":
        return "week"
    if task_spec.time_sensitivity == "medium":
        return "month"
    return None


def _resolve_provider_timeout_seconds(mode: str) -> float:
    if mode == "fast":
        return 30.0
    if mode == "deep":
        return 60.0
    return 30.0


def _plans_for_round(
    *,
    task_spec: SearchTaskSpec,
    round_no: int,
    existing_article_urls: list[str],
    recall_candidates: list[SearchCandidate],
    forced_include_domains: list[str],
) -> tuple[SearchQueryPlan, SearchQueryPlan]:
    """为 Exa 和 Tavily 各生成一条 query plan。

    Round 1: 两个 provider 都用 rewritten_query（广撒网）。
    Round 2+: 从 intent 的 query_plans 中分配不同角度的 plan。
    """

    exclude_domains = _build_exclude_domains(existing_article_urls)
    exclude_paths = _build_tavily_exclude_paths(existing_article_urls)
    base_query = _safe_text(task_spec.rewritten_query)
    plans = task_spec.query_plans or []

    site_suffix = ""
    if forced_include_domains:
        site_suffix = " ".join(f"site:{domain}" for domain in forced_include_domains[:4])

    def _make_plan(key: str, query: str, intent: str) -> SearchQueryPlan:
        full_query = f"{query} {site_suffix}".strip() if site_suffix else query
        return SearchQueryPlan(
            key=key, query=full_query, intent=intent,
            exclude_domains=exclude_domains, exclude_paths=exclude_paths,
        )

    if round_no == 1:
        exa_plan = SearchQueryPlan(
            key=f"exa_round_{round_no}",
            query=base_query,
            intent="base",
            exclude_domains=[],
            exclude_paths=[],
        )
        tavily_plan = SearchQueryPlan(
            key=f"tavily_round_{round_no}",
            query=base_query,
            intent="base",
            exclude_domains=[],
            exclude_paths=[],
        )
    else:
        plan_idx = (round_no - 2) * 2
        exa_src = plans[plan_idx] if plan_idx < len(plans) else None
        tavily_src = plans[plan_idx + 1] if (plan_idx + 1) < len(plans) else None
        exa_plan = _make_plan(
            f"exa_round_{round_no}",
            exa_src.query if exa_src else base_query,
            exa_src.intent if exa_src else "expand",
        )
        tavily_plan = _make_plan(
            f"tavily_round_{round_no}",
            tavily_src.query if tavily_src else base_query,
            tavily_src.intent if tavily_src else "expand",
        )

    return exa_plan, tavily_plan


# ---------------------------------------------------------------------------
# 提供商调用
# ---------------------------------------------------------------------------

async def _search_with_exa(
    *,
    exa_api_key: str | None,
    mode: str,
    task_spec: SearchTaskSpec,
    query_plan: SearchQueryPlan,
    include_domains: list[str] | None = None,
    disable_excludes: bool = False,
    max_results: int = 10,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not exa_api_key:
        return []
    client = ExaSearchClient()
    try:
        result = await client.search(
            ExaSearchRequest(
                query=query_plan.query,
                mode="deep" if mode == "deep" else "auto",
                max_results=max_results,
                freshness_hours=_resolve_exa_max_age_hours(task_spec),
                include_domains=include_domains,
                exclude_domains=None if disable_excludes or include_domains else (query_plan.exclude_domains or None),
                timeout_seconds=_resolve_provider_timeout_seconds(mode),
            ),
            api_key=exa_api_key,
        )
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for row in result.get("results", []):
        url = _safe_text(row.get("url"))
        if not url:
            continue
        domain = _domain_from_url(url)
        candidates.append(SearchCandidate(
            title=_safe_text(row.get("title")) or url,
            url=url,
            domain=domain,
            description=_safe_text(row.get("summary")) or _safe_text(row.get("description")),
            author=_safe_text(row.get("author")) or None,
            published_at=_parse_datetime(row.get("publishedDate")),
            highlights=_safe_highlights(row.get("highlights")),
            provider="exa",
            query_key=query_plan.key,
            preferred_site_hit=is_preferred,
        ))
    return candidates


async def _search_with_tavily(
    *,
    tavily_api_key: str | None,
    mode: str,
    task_spec: SearchTaskSpec,
    query_plan: SearchQueryPlan,
    include_domains: list[str] | None = None,
    disable_excludes: bool = False,
    max_results: int = 10,
    is_preferred: bool = False,
) -> list[SearchCandidate]:
    if not tavily_api_key:
        return []
    client = TavilySearchClient()
    try:
        result = await client.search(
            TavilySearchRequest(
                query=query_plan.query,
                search_depth="advanced",
                max_results=max_results,
                include_domains=include_domains or [],
                exclude_domains=[] if disable_excludes or include_domains else query_plan.exclude_domains,
                exclude_paths=[] if disable_excludes else query_plan.exclude_paths,
                time_range=_resolve_tavily_time_range(task_spec),
                include_raw_content=False,
                timeout_seconds=_resolve_provider_timeout_seconds(mode),
            ),
            api_key=tavily_api_key,
        )
    finally:
        await client.close()

    candidates: list[SearchCandidate] = []
    for row in result.get("results", []):
        url = _safe_text(row.get("url"))
        if not url:
            continue
        domain = _domain_from_url(url)
        content = _safe_text(row.get("content"))
        highlights = _tavily_content_to_highlights(content)
        candidates.append(SearchCandidate(
            title=_safe_text(row.get("title")) or url,
            url=url,
            domain=domain,
            description=content[:280],
            author=None,
            published_at=_parse_datetime(row.get("published_date")),
            highlights=highlights,
            provider="tavily",
            query_key=query_plan.key,
            preferred_site_hit=is_preferred,
        ))
    return candidates


def _tavily_content_to_highlights(content: str) -> list[str]:
    clean = re.sub(r"\s+", " ", content or "").strip()
    if not clean:
        return []
    chunks = [clean[i:i + 420] for i in range(0, min(len(clean), 840), 420)]
    return [chunk.strip() for chunk in chunks[:2] if chunk.strip()]


# ---------------------------------------------------------------------------
# 候选合并与去重
# ---------------------------------------------------------------------------

def _merge_candidates(
    *,
    existing: list[SearchCandidate],
    seen_urls: set[str],
    new_candidates: list[SearchCandidate],
) -> tuple[list[SearchCandidate], set[str]]:
    merged = {_normalize_url(item.url): item for item in existing}
    for candidate in new_candidates:
        normalized = _normalize_url(candidate.url)
        if not normalized or normalized in seen_urls:
            continue
        if normalized in merged:
            current = merged[normalized]
            if _is_preferred_candidate(candidate, current):
                merged[normalized] = candidate
            continue
        duplicate_key = _find_semantic_duplicate_key(candidate, merged)
        if duplicate_key:
            current = merged[duplicate_key]
            if _is_preferred_candidate(candidate, current):
                merged[duplicate_key] = candidate
            seen_urls.add(normalized)
            continue
        merged[normalized] = candidate
        seen_urls.add(normalized)
    return list(merged.values()), seen_urls


def _is_preferred_candidate(left: SearchCandidate, right: SearchCandidate) -> bool:
    """同 URL 或近似语义候选冲突时，优先保留质量更高的结果。"""
    left_signal = _candidate_quality_signal(left)
    right_signal = _candidate_quality_signal(right)
    if abs(left_signal - right_signal) >= 0.08:
        return left_signal > right_signal
    return len(" ".join(left.highlights)) > len(" ".join(right.highlights))


def _candidate_quality_signal(candidate: SearchCandidate) -> float:
    from app.modules.agent.search.nodes.score import _authority_score, _freshness_score

    authority = _authority_score(candidate.domain)
    content_depth = min(len(" ".join(candidate.highlights) or candidate.description) / 480.0, 1.0)
    recency = _freshness_score(candidate.published_at, "medium")
    provider_bonus = 0.05 if candidate.provider == "exa" else 0.03 if candidate.provider == "tavily" else 0.0
    return _clamp(authority * 0.45 + content_depth * 0.35 + recency * 0.2 + provider_bonus)


def _find_semantic_duplicate_key(candidate: SearchCandidate, merged: dict[str, SearchCandidate]) -> str | None:
    candidate_fp = _candidate_semantic_fingerprint(candidate)
    if not candidate_fp:
        return None
    for key, current in merged.items():
        current_fp = _candidate_semantic_fingerprint(current)
        if not current_fp:
            continue
        similarity = _token_similarity(candidate_fp, current_fp)
        if similarity >= 0.86:
            return key
    return None


def _candidate_semantic_fingerprint(candidate: SearchCandidate) -> str:
    title = _safe_text(candidate.title).lower()
    highlight = _safe_text(" ".join(candidate.highlights[:1]) or candidate.description).lower()
    return re.sub(r"\s+", " ", f"{title} {highlight}").strip()
