"""摘要缓存表模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, UUIDPrimaryKeyMixin


class SummaryCache(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "summary_caches"  # type: ignore[assignment]
    __table_args__ = {"comment": "文章摘要缓存表"}

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
