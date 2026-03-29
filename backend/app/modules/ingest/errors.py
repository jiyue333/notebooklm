"""Ingest pipeline 错误类型与统一映射。"""

from __future__ import annotations


class IngestPipelineError(RuntimeError):
    """可结构化识别的 ingest 错误。"""

    def __init__(
        self,
        tag: str,
        message: str,
        *,
        retryable: bool = False,
        phase: str | None = None,
    ) -> None:
        super().__init__(message)
        self.tag = tag
        self.message = message
        self.retryable = retryable
        self.phase = phase or "ingest"


class FetchContentError(IngestPipelineError):
    def __init__(self, tag: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(tag=tag, message=message, retryable=retryable, phase="fetch")


class UnsupportedContentTypeError(IngestPipelineError):
    def __init__(self, *, mime_type: str, file_name: str | None = None) -> None:
        display_name = file_name or "未知文件"
        super().__init__(
            tag="unsupported_content_type",
            message=f"不支持的来源类型（mime={mime_type}，file={display_name}）",
            retryable=False,
            phase="detect",
        )


class InvalidIngestInputError(IngestPipelineError):
    def __init__(self, message: str) -> None:
        super().__init__(
            tag="invalid_ingest_input",
            message=message,
            retryable=False,
            phase="ingest_input",
        )
