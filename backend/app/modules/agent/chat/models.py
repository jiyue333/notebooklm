"""聊天会话与消息表模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notebooks.models import Article, Notebook


class Conversation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversations"  # type: ignore[assignment]
    __table_args__ = {"comment": "聊天会话表"}

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属用户 ID",
    )
    notebook_id: Mapped[str] = mapped_column(
        ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属笔记本 ID",
    )
    current_article_id: Mapped[str | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, comment="当前关联文章 ID",
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True, comment="会话标题")
    rolling_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="滚动摘要")
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后一条消息时间",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="更新时间")

    user: Mapped["User"] = relationship()
    notebook: Mapped["Notebook"] = relationship()
    current_article: Mapped["Article | None"] = relationship()
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
    )


class ConversationMessage(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "conversation_messages"  # type: ignore[assignment]
    __table_args__ = {"comment": "聊天消息表"}

    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True, comment="所属会话 ID",
    )
    article_id: Mapped[str | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), nullable=True, comment="关联文章 ID",
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="消息角色")  # 角色值："user" | "assistant"
    route: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="回答路由")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    retrieval_snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="检索快照 JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
