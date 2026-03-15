"""Create summary_caches table for AI summary cache.

Revision ID: 20260315_0012
Revises: 20260315_0011
Create Date: 2026-03-15

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260315_0012"
down_revision = "20260315_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summary_caches",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("output_language", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summary_caches")),
        sa.UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            name="uq_summary_caches_identity",
        ),
    )
    op.create_index(op.f("ix_summary_caches_article_id"), "summary_caches", ["article_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_summary_caches_article_id"), table_name="summary_caches")
    op.drop_table("summary_caches")
