"""摘要缓存表模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, UUIDPrimaryKeyMixin


class SummaryCache(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "summary_caches"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "model_provider",
            "model_name",
            "output_language",
            name="uq_summary_caches_runtime_identity",
        ),
        {"comment": "文章摘要缓存表"},
    )

    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文章 ID",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="正文内容哈希")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, comment="提示词版本")
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False, comment="模型提供方")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="模型名称")
    output_language: Mapped[str] = mapped_column(String(16), nullable=False, default="auto", comment="输出语言")
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, comment="摘要正文")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")


class SummaryCompressionCache(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "summary_compression_caches"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "article_type",
            "compress_version",
            "compress_code_blocks",
            name="uq_summary_compression_identity",
        ),
        {"comment": "摘要压缩内容缓存表"},
    )

    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文章 ID",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="正文内容哈希")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, comment="提示词版本")
    article_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="文档类型")
    compress_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1", comment="压缩策略版本")
    compress_code_blocks: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否压缩代码块")
    compressed_content: Mapped[str] = mapped_column(Text, nullable=False, comment="压缩后的内容")
    original_length: Mapped[int] = mapped_column(Integer, nullable=False, comment="原文长度")
    compressed_length: Mapped[int] = mapped_column(Integer, nullable=False, comment="压缩后长度")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")


class SummaryGenerationAudit(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "summary_generation_audits"  # type: ignore[assignment]
    __table_args__ = {"comment": "摘要生成审计日志"}

    article_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文章 ID",
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="正文内容哈希")
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, comment="提示词版本")
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False, comment="模型提供方")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="模型名称")
    output_language: Mapped[str] = mapped_column(String(16), nullable=False, comment="输出语言")
    status: Mapped[str] = mapped_column(String(24), nullable=False, comment="生成状态")
    summary_strategy: Mapped[str] = mapped_column(String(24), nullable=False, default="direct", comment="摘要策略")
    article_type: Mapped[str] = mapped_column(String(32), nullable=False, default="general", comment="文档类型")
    validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否通过校验")
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否使用降级")
    fallback_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="", comment="降级原因")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="重试次数")
    summary_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="摘要长度")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="端到端耗时")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误编码")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")
