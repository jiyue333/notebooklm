"""搜索模块 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.auth.models import User
    from app.modules.notebooks.models import Notebook


class SearchSession(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "search_sessions"  # type: ignore[assignment]
    __table_args__ = {"comment": "来源搜索会话表"}

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
    query: Mapped[str] = mapped_column(Text, nullable=False, comment="原始查询词")
    normalized_query: Mapped[str] = mapped_column(Text, nullable=False, comment="归一化查询词")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, comment="搜索模式")
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, comment="执行方式")
    provider_name: Mapped[str] = mapped_column(String(32), nullable=False, comment="搜索提供方")
    provider_request_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="请求参数快照 JSON")
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="会话状态")
    mode_label: Mapped[str] = mapped_column(String(64), nullable=False, comment="模式展示文案")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="结果数量")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="错误代码")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="错误信息")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="完成时间")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="过期时间")

    user: Mapped["User"] = relationship()
    notebook: Mapped["Notebook"] = relationship()
    results: Mapped[list["SearchResult"]] = relationship(
        back_populates="search_session",
        cascade="all, delete-orphan",
    )


class SearchResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "search_results"  # type: ignore[assignment]
    __table_args__ = {"comment": "搜索结果表"}

    search_session_id: Mapped[str] = mapped_column(
        ForeignKey("search_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属搜索会话 ID",
    )
    provider_result_id: Mapped[str | None] = mapped_column(Text, nullable=True, comment="提供方结果 ID")
    raw_url: Mapped[str] = mapped_column(Text, nullable=False, comment="原始链接")
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False, comment="规范化链接")
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="链接哈希")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="结果标题")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="结果摘要")
    author: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作者")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="发布时间")
    domain: Mapped[str | None] = mapped_column(Text, nullable=True, comment="来源域名")
    favicon_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="站点图标链接")
    display_rank: Mapped[int] = mapped_column(Integer, nullable=False, comment="展示排序")
    preview_markdown: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预览 Markdown")
    raw_payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="原始扩展载荷 JSON")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="创建时间")

    search_session: Mapped[SearchSession] = relationship(back_populates="results")
