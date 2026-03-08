"""create p0 auth notebooks notes tables

Revision ID: 20260307_0002
Revises: 20260307_0001
Create Date: 2026-03-07 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260307_0002"
down_revision = "20260307_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("settings_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("llm_api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("llm_api_key_last4", sa.String(length=4), nullable=True),
        sa.Column("llm_api_key_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exa_api_key_ciphertext", sa.Text(), nullable=True),
        sa.Column("exa_api_key_last4", sa.String(length=4), nullable=True),
        sa.Column("exa_api_key_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_users_name", "users", ["name"], unique=True)
    op.create_index("uq_users_email", "users", ["email"], unique=True)

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_tokens_user_id", "auth_tokens", ["user_id"], unique=False)
    op.create_index("uq_auth_tokens_token_hash", "auth_tokens", ["token_hash"], unique=True)

    op.create_table(
        "notebooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notebooks_user_id", "notebooks", ["user_id"], unique=False)

    op.create_table(
        "notes",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("notebook_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("note_type", sa.String(length=64), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_notes_notebook_id", "notes", ["notebook_id"], unique=False)

    op.execute(
        """
        INSERT INTO users (id, name, email, password_hash, avatar_url, settings_json)
        VALUES (
            '00000000-0000-0000-0000-000000000001',
            'taless',
            'taless@example.com',
            'pbkdf2_sha256$600000$bm90ZWJvb2tsbS1kZW1vLXNhbHQ$oY9mFmVTsDfNx6lGnFyD4ZNY4UG1ZYPXgIegz0WkBRw',
            NULL,
            '{}'::jsonb
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notes_notebook_id", table_name="notes")
    op.drop_table("notes")
    op.drop_index("ix_notebooks_user_id", table_name="notebooks")
    op.drop_table("notebooks")
    op.drop_index("uq_auth_tokens_token_hash", table_name="auth_tokens")
    op.drop_index("ix_auth_tokens_user_id", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_index("uq_users_email", table_name="users")
    op.drop_index("uq_users_name", table_name="users")
    op.drop_table("users")
