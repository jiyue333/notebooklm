"""create search sessions and results

Revision ID: 20260308_0003
Revises: 20260307_0002
Create Date: 2026-03-08 00:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260308_0003"
down_revision = "20260307_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("normalized_query", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False),
        sa.Column("provider_request_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("mode_label", sa.String(length=64), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_search_sessions_user_id", "search_sessions", ["user_id"], unique=False)
    op.create_index("ix_search_sessions_notebook_id", "search_sessions", ["notebook_id"], unique=False)

    op.create_table(
        "search_results",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("search_session_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("search_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_result_id", sa.Text(), nullable=True),
        sa.Column("raw_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("favicon_url", sa.Text(), nullable=True),
        sa.Column("display_rank", sa.Integer(), nullable=False),
        sa.Column("preview_markdown", sa.Text(), nullable=True),
        sa.Column("raw_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_results_search_session_id", "search_results", ["search_session_id"], unique=False)
    op.create_index("ix_search_results_url_hash", "search_results", ["url_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_search_results_url_hash", table_name="search_results")
    op.drop_index("ix_search_results_search_session_id", table_name="search_results")
    op.drop_table("search_results")
    op.drop_index("ix_search_sessions_notebook_id", table_name="search_sessions")
    op.drop_index("ix_search_sessions_user_id", table_name="search_sessions")
    op.drop_table("search_sessions")
