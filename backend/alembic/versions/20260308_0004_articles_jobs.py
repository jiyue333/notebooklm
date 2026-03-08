"""create articles and jobs tables

Revision ID: 20260308_0004
Revises: 20260308_0003
Create Date: 2026-03-08 00:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260308_0004"
down_revision = "20260308_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "articles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("input_type", sa.String(length=32), nullable=False),
        sa.Column("origin_search_session_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("search_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("origin_search_result_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("search_results.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("normalized_url", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=64), nullable=False),
        sa.Column("source_title_raw", sa.Text(), nullable=True),
        sa.Column("raw_text_input", sa.Text(), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("file_ext", sa.String(length=32), nullable=True),
        sa.Column("file_mime", sa.String(length=128), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("file_storage_key", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("preview_markdown", sa.Text(), nullable=True),
        sa.Column("clean_markdown", sa.Text(), nullable=True),
        sa.Column("toc_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("parser_name", sa.String(length=64), nullable=True),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("parse_error_tag", sa.String(length=64), nullable=True),
        sa.Column("parse_error_message", sa.Text(), nullable=True),
        sa.Column("parse_quality_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("article_retrieval_text", sa.Text(), nullable=True),
        sa.Column("chunk_status", sa.String(length=16), nullable=False),
        sa.Column("index_status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_articles_user_id", "articles", ["user_id"], unique=False)
    op.create_index("ix_articles_notebook_id", "articles", ["notebook_id"], unique=False)
    op.create_index("uq_articles_notebook_dedupe", "articles", ["user_id", "notebook_id", "dedupe_key"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=True),
        sa.Column("search_session_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("search_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_jobs_article_id", "jobs", ["article_id"], unique=False)
    op.create_index("ix_jobs_search_session_id", "jobs", ["search_session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_search_session_id", table_name="jobs")
    op.drop_index("ix_jobs_article_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("uq_articles_notebook_dedupe", table_name="articles")
    op.drop_index("ix_articles_notebook_id", table_name="articles")
    op.drop_index("ix_articles_user_id", table_name="articles")
    op.drop_table("articles")
