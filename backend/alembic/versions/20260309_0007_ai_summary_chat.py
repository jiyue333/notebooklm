"""add summary cache and chat persistence tables

Revision ID: 20260309_0007
Revises: 20260308_0006
Create Date: 2026-03-09 14:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260309_0007"
down_revision = "20260308_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "summary_cache",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("output_language", sa.String(length=64), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_summary_cache")),
        sa.UniqueConstraint(
            "article_id",
            "content_hash",
            "prompt_version",
            "model_provider",
            "model_name",
            "output_language",
            name="uq_summary_cache_identity",
        ),
    )
    op.create_index(op.f("ix_summary_cache_user_id"), "summary_cache", ["user_id"], unique=False)
    op.create_index(op.f("ix_summary_cache_article_id"), "summary_cache", ["article_id"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("current_article_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("rolling_summary", sa.Text(), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["current_article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"], unique=False)
    op.create_index(op.f("ix_conversations_notebook_id"), "conversations", ["notebook_id"], unique=False)
    op.create_index(op.f("ix_conversations_current_article_id"), "conversations", ["current_article_id"], unique=False)

    op.create_table(
        "conversation_messages",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("route", sa.String(length=32), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("retrieval_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        op.f("ix_conversation_messages_conversation_id"),
        "conversation_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conversation_messages_article_id"),
        "conversation_messages",
        ["article_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversation_messages_article_id"), table_name="conversation_messages")
    op.drop_index(op.f("ix_conversation_messages_conversation_id"), table_name="conversation_messages")
    op.drop_table("conversation_messages")

    op.drop_index(op.f("ix_conversations_current_article_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_notebook_id"), table_name="conversations")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")

    op.drop_index(op.f("ix_summary_cache_article_id"), table_name="summary_cache")
    op.drop_index(op.f("ix_summary_cache_user_id"), table_name="summary_cache")
    op.drop_table("summary_cache")
