from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
