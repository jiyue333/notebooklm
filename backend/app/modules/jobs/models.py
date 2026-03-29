from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class JobDeadLetter(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "job_dead_letters"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_job_dead_letters_job_id"),
        {"comment": "任务死信队列表"},
    )

    job_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True, comment="原任务 ID")
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="任务类型")
    article_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True, index=True, comment="关联文章 ID")
    search_session_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        nullable=True,
        index=True,
        comment="关联搜索会话 ID",
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, comment="去重键")
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="任务载荷快照")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已尝试次数")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, comment="最大尝试次数")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最终错误信息")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误代码")
    dead_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="attempts_exhausted", comment="死信原因")
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="重投次数")
    last_replay_job_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        nullable=True,
        comment="最近一次重投任务 ID",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="原任务创建时间")
    dead_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="进入死信时间")
    replayed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次重投时间",
    )
