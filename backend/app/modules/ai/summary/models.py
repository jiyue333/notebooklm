from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SummaryCache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "summary_cache"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "model_provider",
            "model_name",
            "output_language",
            name="uq_summary_cache_identity",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    output_language: Mapped[str] = mapped_column(String(64), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)

