from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RssFeed(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "rss_feeds"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("user_id", "miniflux_feed_id"),
        Index("idx_rss_feeds_user", "user_id"),
        {"comment": "用户 RSS 订阅源关联表"},
    )

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属用户 ID",
    )
    miniflux_feed_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="Miniflux Feed ID")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="显示标题")
    feed_url: Mapped[str] = mapped_column(Text, nullable=False, comment="RSS 地址")
    site_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="站点主页")
    category_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="分类名称")
    icon_data: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Feed favicon Base64 缓存")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
    crawler_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否启用全文抓取")


class RssHistoryEntry(TimestampMixin, Base):
    __tablename__ = "rss_history_entries"  # type: ignore[assignment]
    __table_args__ = (
        UniqueConstraint("user_id", "feed_id", "dedupe_key"),
        Index("idx_rss_history_entries_user_feed", "user_id", "feed_id"),
        Index("idx_rss_history_entries_feed_published", "feed_id", "published_at"),
        {"comment": "用户主动回填的 RSS 历史文章"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键 ID")
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属用户 ID",
    )
    feed_id: Mapped[str] = mapped_column(
        ForeignKey("rss_feeds.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属 RSS 订阅源 ID",
    )
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False, comment="历史文章去重键")
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True, comment="原文链接")
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="标题")
    author: Mapped[str | None] = mapped_column(Text, nullable=True, comment="作者")
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="发布时间",
    )
    content_html: Mapped[str | None] = mapped_column(Text, nullable=True, comment="抓取到的正文 HTML")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unread", comment="阅读状态")
    starred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否星标")
