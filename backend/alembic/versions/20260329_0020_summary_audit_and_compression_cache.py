"""Add summary compression cache and generation audit tables.

Revision ID: 20260329_0020
Revises: 20260328_0019
Create Date: 2026-03-29

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260329_0020"
down_revision = "20260329_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summary_compression_caches",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("article_type", sa.String(length=32), nullable=False),
        sa.Column("compress_version", sa.String(length=32), nullable=False, server_default="v1"),
        sa.Column("compress_code_blocks", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("compressed_content", sa.Text(), nullable=False),
        sa.Column("original_length", sa.Integer(), nullable=False),
        sa.Column("compressed_length", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summary_compression_caches")),
        sa.UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "article_type",
            "compress_version",
            "compress_code_blocks",
            name="uq_summary_compression_identity",
        ),
        comment="摘要压缩内容缓存表",
    )
    op.create_index(
        op.f("ix_summary_compression_caches_article_id"),
        "summary_compression_caches",
        ["article_id"],
        unique=False,
    )

    op.create_table(
        "summary_generation_audits",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("output_language", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary_strategy", sa.String(length=24), nullable=False, server_default="direct"),
        sa.Column("article_type", sa.String(length=32), nullable=False, server_default="general"),
        sa.Column("validation_passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fallback_reason", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary_length", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summary_generation_audits")),
        comment="摘要生成审计日志",
    )
    op.create_index(
        op.f("ix_summary_generation_audits_article_id"),
        "summary_generation_audits",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_summary_generation_audits_status"),
        "summary_generation_audits",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_summary_generation_audits_status"), table_name="summary_generation_audits")
    op.drop_index(op.f("ix_summary_generation_audits_article_id"), table_name="summary_generation_audits")
    op.drop_table("summary_generation_audits")

    op.drop_index(op.f("ix_summary_compression_caches_article_id"), table_name="summary_compression_caches")
    op.drop_table("summary_compression_caches")
