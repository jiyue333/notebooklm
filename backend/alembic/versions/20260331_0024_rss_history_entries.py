"""add rss history entries table

Revision ID: 20260331_0024
Revises: 20260329_0023
Create Date: 2026-03-31 18:20:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260331_0024"
down_revision = "20260329_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_history_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),  # pragma: allowlist secret
        sa.Column("feed_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("rss_feeds.id", ondelete="CASCADE"), nullable=False),  # pragma: allowlist secret
        sa.Column("dedupe_key", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_html", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="unread"),
        sa.Column("starred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "feed_id", "dedupe_key", name="uq_rss_history_entries_user_feed_dedupe_key"),
    )
    op.create_index(
        "idx_rss_history_entries_user_feed",
        "rss_history_entries",
        ["user_id", "feed_id"],
    )
    op.create_index(
        "idx_rss_history_entries_feed_published",
        "rss_history_entries",
        ["feed_id", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_rss_history_entries_feed_published", table_name="rss_history_entries")
    op.drop_index("idx_rss_history_entries_user_feed", table_name="rss_history_entries")
    op.drop_table("rss_history_entries")
