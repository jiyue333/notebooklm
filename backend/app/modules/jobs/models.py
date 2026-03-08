from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, UUIDPrimaryKeyMixin


class Job(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "jobs"  # type: ignore[assignment]

    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    article_id: Mapped[str | None] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    search_session_id: Mapped[str | None] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
