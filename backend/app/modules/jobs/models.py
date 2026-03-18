from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "jobs"  # type: ignore[assignment]
    __table_args__ = {"comment": "异步任务表"}

    job_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")
    article_id: Mapped[str | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联文章 ID",
    )
    search_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联搜索会话 ID",
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="去重键")
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="任务载荷 JSON")
    status: Mapped[str] = mapped_column(String(32), nullable=False, comment="任务状态")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已尝试次数")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, comment="最大重试次数")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近一次错误")
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="链路追踪 ID")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="可执行时间")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="开始执行时间")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="结束执行时间")
