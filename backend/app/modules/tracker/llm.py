"""AI / LLM 调用的可观测性聚合 Tracker。

覆盖文件：
- ai/chat/runner.py
- ai/chat/rollup.py
- ai/chat/service.py
- ai/summary/service.py
- ingest/parsers/llm_markdown_fallback.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from app.infra.telemetry.metrics import (
    observe_ai_first_token,
    observe_ai_request,
    observe_ai_response_length,
    observe_ai_stream,
    observe_llm_call,
)
from app.modules.tracker.stage_timer import elapsed_ms


@dataclass(slots=True)
class LlmTracker:
    """聚合一次 LLM 操作的所有可观测性上报。

    将重复的 ``operation`` / ``provider`` / ``model`` 参数收拢到
    对象内部，对外暴露语义清晰的高层方法。

    典型用法::

        tracker = LlmTracker.from_model_settings("chat", prepared.model_settings)
        tracker.mark_llm_start()
        try:
            result = await model.ainvoke(...)
        except Exception:
            tracker.report_llm("error")
            raise
        tracker.report_llm("success", usage=usage)

    流式模式::

        tracker = LlmTracker.from_model_settings("summary", prepared.model_settings)
        ...
        tracker.report_stream_success(response_length=len(summary))
        # 自动合并 llm + stream + request + response_length 四项上报
    """

    operation: str
    provider: str = ""
    model: str = ""
    _request_started: float = field(default_factory=perf_counter)
    _llm_started: float | None = field(default=None, repr=False)

    # ---- 快捷构造 ----

    @classmethod
    def from_model_settings(cls, operation: str, settings: dict) -> LlmTracker:
        """从 ``get_user_generation_settings()`` 返回的 dict 构造。"""
        return cls(
            operation=operation,
            provider=settings["modelProvider"],
            model=settings["modelName"],
        )

    # ---- 计时 ----

    def mark_llm_start(self) -> None:
        """标记 LLM 调用开始时间点。"""
        self._llm_started = perf_counter()

    @property
    def request_ms(self) -> float:
        """从 Tracker 创建到当前时刻的耗时（请求级别）。"""
        return elapsed_ms(self._request_started)

    @property
    def llm_ms(self) -> float:
        """从 :meth:`mark_llm_start` 到当前时刻的耗时（LLM 调用级别）。"""
        if self._llm_started is None:
            return 0.0
        return elapsed_ms(self._llm_started)

    # ---- 低层上报：每个对应一个 observe_* ----

    def report_llm(self, status: str, *, usage: dict | None = None) -> None:
        """上报 ``observe_llm_call``。"""
        observe_llm_call(
            operation=self.operation,
            provider=self.provider,
            model=self.model,
            status=status,
            duration_ms=self.llm_ms,
            usage=usage,
        )

    def report_request(self, mode: str, status: str) -> None:
        """上报 ``observe_ai_request``。"""
        observe_ai_request(
            operation=self.operation,
            mode=mode,
            status=status,
            duration_ms=self.request_ms,
        )

    def report_first_token(self, duration_ms: float) -> None:
        """上报 ``observe_ai_first_token``。"""
        observe_ai_first_token(
            operation=self.operation,
            provider=self.provider,
            model=self.model,
            duration_ms=duration_ms,
        )

    def report_stream(self, status: str) -> None:
        """上报 ``observe_ai_stream``。"""
        observe_ai_stream(
            operation=self.operation,
            provider=self.provider,
            model=self.model,
            status=status,
            duration_ms=self.llm_ms,
        )

    def report_response_length(self, length: int) -> None:
        """上报 ``observe_ai_response_length``。"""
        observe_ai_response_length(operation=self.operation, length=length)

    # ---- 组合便捷方法：同步模式 ----

    def report_sync_error(self) -> None:
        """同步模式错误：LLM error + Request error。"""
        if self._llm_started is not None:
            self.report_llm("error")
        self.report_request("sync", "error")

    def report_sync_success(
        self,
        *,
        usage: dict | None = None,
        response_length: int = 0,
    ) -> None:
        """同步模式成功：LLM success + Request success + Response length。"""
        if self._llm_started is not None:
            self.report_llm("success", usage=usage)
        self.report_request("sync", "success")
        if response_length:
            self.report_response_length(response_length)

    # ---- 组合便捷方法：流式模式 ----

    def report_stream_error(self) -> None:
        """流式模式错误：LLM error + Stream error + Request error。"""
        if self._llm_started is not None:
            self.report_llm("error")
            self.report_stream("error")
        self.report_request("stream", "error")

    def report_stream_success(self, *, response_length: int = 0) -> None:
        """流式模式成功：LLM success + Stream success + Request success + Response length。"""
        if self._llm_started is not None:
            self.report_llm("success")
            self.report_stream("success")
        self.report_request("stream", "success")
        if response_length:
            self.report_response_length(response_length)
