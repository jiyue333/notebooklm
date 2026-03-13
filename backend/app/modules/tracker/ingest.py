"""Ingest Pipeline 的可观测性 Tracker。

覆盖文件：
- ingest/articles/worker.py
- ingest/indexing/pipeline.py
- ingest/articles/content.py

继承 StageTimer，自动维护 ``input_type`` 标签，
将 8-12 行的 "计时 + span + observe_ingest_stage" 三连压缩为一个 ``with`` 块。
"""

from __future__ import annotations

from app.infra.telemetry.metrics import (
    observe_ingest_doc_type,
    observe_ingest_doc_type_quality_score,
    observe_ingest_doc_type_structure_score,
    observe_ingest_chunks,
    observe_ingest_fallback,
    observe_ingest_parse,
    observe_ingest_quality_score,
    observe_ingest_ready,
    observe_ingest_stage,
    observe_ingest_structure_score,
)
from app.modules.tracker.stage_timer import StageTimer


class IngestTracker(StageTimer):
    """Ingest pipeline 的 stage + 质量 + 解析上报。

    用法::

        tracker = IngestTracker(input_type=article.input_type)

        with tracker.stage("fetch", span_attrs={"fetch_strategy": "exa_contents"}) as ctx:
            markdown, parser_name = await fetch_markdown_with_exa(...)
            if not markdown:
                ctx.status = "empty"

        with tracker.stage("clean"):
            markdown = clean_markdown(markdown)

        tracker.report_quality(score=quality.score)
    """

    def __init__(self, input_type: str, *, document_type: str = "unknown") -> None:
        super().__init__(span_prefix="ingest")
        self.input_type = input_type
        self.document_type = document_type

    def set_document_type(self, document_type: str) -> None:
        self.document_type = document_type

    # ---- StageTimer 抽象方法实现 ----

    def _base_span_attrs(self) -> dict[str, str]:
        return {"input_type": self.input_type, "document_type": self.document_type}

    def _report_stage(self, name: str, status: str, duration_ms: float) -> None:
        observe_ingest_stage(
            stage=name,
            input_type=self.input_type,
            status=status,
            duration_ms=duration_ms,
        )

    # ---- Ingest 领域特有上报 ----

    def report_parse(
        self,
        *,
        status: str,
        parser: str,
        error_tag: str = "none",
    ) -> None:
        """上报 ``observe_ingest_parse``。"""
        observe_ingest_parse(
            input_type=self.input_type,
            status=status,
            parser=parser,
            error_tag=error_tag,
        )
        observe_ingest_doc_type(doc_type=self.document_type, status=status)

    def report_fallback(self, fallback_type: str) -> None:
        """上报 ``observe_ingest_fallback``。"""
        observe_ingest_fallback(fallback_type=fallback_type)

    def report_chunks(self, chunk_count: int) -> None:
        """上报 ``observe_ingest_chunks``。"""
        observe_ingest_chunks(
            input_type=self.input_type,
            chunk_count=chunk_count,
        )

    def report_quality(self, score: float) -> None:
        """上报 ``observe_ingest_quality_score``。"""
        observe_ingest_quality_score(
            input_type=self.input_type,
            score=score,
        )
        observe_ingest_doc_type_quality_score(doc_type=self.document_type, score=score)

    def report_structure(self, structure_type: str, score: float) -> None:
        """上报 ``observe_ingest_structure_score``。"""
        observe_ingest_structure_score(
            input_type=self.input_type,
            structure_type=structure_type,
            score=score,
        )
        observe_ingest_doc_type_structure_score(
            doc_type=self.document_type,
            structure_type=structure_type,
            score=score,
        )

    def report_ready(self, duration_ms: float) -> None:
        """上报 ``observe_ingest_ready``。"""
        observe_ingest_ready(
            input_type=self.input_type,
            duration_ms=duration_ms,
        )
