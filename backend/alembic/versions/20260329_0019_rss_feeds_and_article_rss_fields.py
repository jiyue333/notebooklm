"""add rss feeds table and article rss fields

Revision ID: 20260329_0019
Revises: 20260328_0019
Create Date: 2026-03-29 09:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260329_0019"
down_revision = "20260328_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_feeds",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),  # pragma: allowlist secret
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),  # pragma: allowlist secret
        sa.Column("miniflux_feed_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("site_url", sa.Text(), nullable=True),
        sa.Column("category_name", sa.String(length=128), nullable=True),
        sa.Column("icon_data", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("crawler_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "miniflux_feed_id", name="uq_rss_feeds_user_miniflux_feed"),
    )
    op.create_index("idx_rss_feeds_user", "rss_feeds", ["user_id"])

    op.add_column(
        "articles",
        sa.Column(
            "rss_feed_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
            comment="RSS 订阅源 ID",
        ),
    )
    op.add_column(
        "articles",
        sa.Column("rss_entry_id", sa.Integer(), nullable=True, comment="Miniflux Entry ID"),
    )
    op.create_foreign_key(
        "fk_articles_rss_feed_id_rss_feeds",
        "articles",
        "rss_feeds",
        ["rss_feed_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_articles_rss_feed_id", "articles", ["rss_feed_id"])
    op.create_index("ix_articles_rss_entry_id", "articles", ["rss_entry_id"])


def downgrade() -> None:
    op.drop_index("ix_articles_rss_entry_id", table_name="articles")
    op.drop_index("ix_articles_rss_feed_id", table_name="articles")
    op.drop_constraint("fk_articles_rss_feed_id_rss_feeds", "articles", type_="foreignkey")
    op.drop_column("articles", "rss_entry_id")
    op.drop_column("articles", "rss_feed_id")

    op.drop_index("idx_rss_feeds_user", table_name="rss_feeds")
    op.drop_table("rss_feeds")
