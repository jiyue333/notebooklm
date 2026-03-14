"""Search Session 的可观测性 Tracker。

覆盖文件：
- search/sessions/service.py

继承 StageTimer，自动维护 ``mode`` / ``execution`` / ``provider`` 标签，
将 execute_search 中 ~120 行的 stage 计时 + 质量批量上报压缩为简洁调用。
"""

from __future__ import annotations

from app.infra.telemetry.metrics import (
    observe_search_provider,
    observe_search_request,
    observe_search_result_count,
    observe_search_result_score,
    observe_search_result_signal,
    observe_search_stage,
)
from app.modules.search.sessions.dto import SearchCandidateDTO
from app.modules.search.sessions.quality import SearchQualitySnapshot
from app.modules.tracker.search_review import SearchReviewTracker
from app.modules.tracker.stage_timer import StageTimer


class SearchTracker(StageTimer):
    """Search pipeline 的 stage + provider + 质量上报。

    用法::

        tracker = SearchTracker(mode="fast", execution="sync", provider="exa")

        with tracker.stage("provider_search"):
            payload = await client.search(request, api_key=exa_api_key)

        with tracker.stage("result_map"):
            candidates = ExaResultMapper.map_search_results(payload)

        tracker.report_result_count(len(candidates))
        tracker.report_quality(quality_snapshot)
    """

    def __init__(
        self,
        *,
        mode: str,
        execution: str,
        provider: str,
    ) -> None:
        super().__init__(span_prefix="search")
        self.mode = mode
        self.execution = execution
        self.provider = provider

    # ---- StageTimer 抽象方法实现 ----

    def _base_span_attrs(self) -> dict[str, str]:
        return {
            "search.mode": self.mode,
            "search.execution": self.execution,
            "provider": self.provider,
        }

    def _report_stage(self, name: str, status: str, duration_ms: float) -> None:
        observe_search_stage(
            stage=name,
            mode=self.mode,
            execution=self.execution,
            status=status,
            duration_ms=duration_ms,
        )

    # ---- Search 领域特有上报 ----

    def report_request(self, status: str) -> None:
        """上报 ``observe_search_request``。"""
        observe_search_request(
            mode=self.mode,
            execution=self.execution,
            status=status,
        )

    def report_provider(self, status: str, duration_ms: float) -> None:
        """上报 ``observe_search_provider``。"""
        observe_search_provider(
            provider=self.provider,
            mode=self.mode,
            status=status,
            duration_ms=duration_ms,
        )

    def report_result_count(self, count: int) -> None:
        """上报 ``observe_search_result_count``。"""
        observe_search_result_count(
            mode=self.mode,
            execution=self.execution,
            result_count=count,
        )

    def report_quality(self, quality_snapshot) -> None:
        """一次性上报所有搜索结果质量分数和信号。

        将原来 ~25 行的循环 + 多次 ``observe_search_result_score`` /
        ``observe_search_result_signal`` 压缩为一次调用。
        """
        for score_type, score_value in (
            ("quality", quality_snapshot.overall),
            ("recency", quality_snapshot.recency),
            ("authority", quality_snapshot.authority),
            ("credibility", quality_snapshot.credibility),
            ("professional", quality_snapshot.professional),
        ):
            observe_search_result_score(
                score_type=score_type,
                mode=self.mode,
                execution=self.execution,
                provider=self.provider,
                score=score_value,
            )
        observe_search_result_signal(
            signal="freshness_satisfied",
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
            result="yes" if quality_snapshot.freshness_satisfied else "no",
        )
        observe_search_result_signal(
            signal="authority_hit",
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
            result="yes" if quality_snapshot.authority_hit else "no",
        )

    async def capture_review_sample(
        self,
        *,
        user=None,
        search_session_id: str,
        notebook_id: str,
        query: str,
        freshness_hours: int | None,
        candidates: list[SearchCandidateDTO],
        quality_snapshot: SearchQualitySnapshot,
    ) -> bool:
        tracker = SearchReviewTracker(
            mode=self.mode,
            execution=self.execution,
            provider=self.provider,
        )
        return await tracker.capture(
            user=user,
            search_session_id=search_session_id,
            notebook_id=notebook_id,
            query=query,
            freshness_hours=freshness_hours,
            candidates=candidates,
            quality_snapshot=quality_snapshot,
        )
