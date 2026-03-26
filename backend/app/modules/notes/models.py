from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB  # pragma: allowlist secret
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.notebooks.models import Notebook


class Note(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notes"  # type: ignore[assignment]
    __table_args__ = {"comment": "笔记表"}

    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属笔记本 ID",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="笔记标题")
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False, comment="Markdown 正文")
    note_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="笔记类型")
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="关联来源数量")
    tags_json: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True, comment="笔记标签 JSON")  # pragma: allowlist secret

    notebook: Mapped["Notebook"] = relationship(back_populates="notes")
