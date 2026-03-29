from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.notebooks.models import Article, Notebook


class ArticleHighlight(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "article_highlights"  # type: ignore[assignment]
    __table_args__ = {"comment": "文章高亮与批注"}

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属笔记本 ID",
    )
    article_id: Mapped[str] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属文章 ID",
    )
    selected_text: Mapped[str] = mapped_column(Text, nullable=False, comment="高亮文本")
    color: Mapped[str] = mapped_column(String(24), nullable=False, default="yellow", comment="高亮颜色")
    comment_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="批注内容")
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="正文字符起始偏移")
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="正文字符结束偏移")
    occurrence_index: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="同文本出现序号(0-based)")

    notebook: Mapped["Notebook"] = relationship()
    article: Mapped["Article"] = relationship()

