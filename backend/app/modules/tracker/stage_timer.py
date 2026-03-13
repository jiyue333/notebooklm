"""通用的 pipeline stage 计时 + span + 上报基类。

被 IngestTracker / SearchTracker 继承使用，也可单独用于自定义 pipeline。
"""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter

from app.infra.telemetry.tracing import start_span


def elapsed_ms(since: float) -> float:
    """计算从 *since* (perf_counter 时间戳) 到当前时刻经过的毫秒数。"""
    return round((perf_counter() - since) * 1000, 2)


class StageCtx:
    """由 ``StageTimer.stage()`` yield 出的可变上下文对象。

    在 ``with`` 块内设置 ``ctx.status`` 可以覆盖默认的 success/error 推断：

    .. code-block:: python

        with tracker.stage("fetch") as ctx:
            markdown = await do_fetch()
            if not markdown:
                ctx.status = "empty"
    """

    __slots__ = ("status", "duration_ms")

    def __init__(self) -> None:
        self.status: str | None = None
        self.duration_ms: float = 0.0


class StageTimer:
    """Pipeline stage 计时 + tracing span + 指标上报的基类。

    子类需要实现 :meth:`_report_stage` 来调用领域对应的 ``observe_*`` 函数，
    以及 :meth:`_base_span_attrs` 来提供共享的 span 属性。

    :param span_prefix: span 名称前缀，实际 span 名 = ``{span_prefix}.{stage_name}``。
    """

    def __init__(self, span_prefix: str) -> None:
        self._span_prefix = span_prefix
        self.timings: dict[str, float] = {}

    # ---- 子类需覆盖 ----

    def _base_span_attrs(self) -> dict[str, str]:
        """返回所有 stage span 共享的属性，如 ``input_type`` 或 ``mode``。"""
        return {}

    def _report_stage(self, name: str, status: str, duration_ms: float) -> None:
        """调用领域对应的 ``observe_*_stage`` 函数。"""
        raise NotImplementedError

    # ---- 公开 API ----

    @contextmanager
    def stage(
        self,
        name: str,
        *,
        span_name: str | None = None,
        span_attrs: dict | None = None,
    ):
        """stage 级别的计时 + span + 上报上下文管理器。

        - 正常退出且 ``ctx.status`` 未被设置时，自动标记为 ``"success"``。
        - 因异常退出且 ``ctx.status`` 未被设置时，自动标记为 ``"error"``。
        - 在 ``with`` 块内部可手动设置 ``ctx.status`` 覆盖默认行为。

        .. code-block:: python

            with tracker.stage("chunk", span_attrs={"article_id": article.id}):
                chunks = chunk_markdown(...)
        """
        ctx = StageCtx()
        started = perf_counter()
        resolved_span = span_name or f"{self._span_prefix}.{name}"
        merged_attrs = {**self._base_span_attrs(), **(span_attrs or {})}

        with start_span(resolved_span, attributes=merged_attrs):
            try:
                yield ctx
            except Exception:
                if ctx.status is None:
                    ctx.status = "error"
                raise
            finally:
                if ctx.status is None:
                    ctx.status = "success"
                ms = elapsed_ms(started)
                ctx.duration_ms = ms
                self.timings[name] = ms
                self._report_stage(name, ctx.status, ms)

    def report_stage_manual(
        self,
        name: str,
        status: str,
        duration_ms: float,
    ) -> None:
        """手动上报一个 stage（不使用上下文管理器时）。"""
        self._report_stage(name, status, duration_ms)
        self.timings[name] = duration_ms
