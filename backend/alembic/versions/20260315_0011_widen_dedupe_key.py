"""Widen articles.dedupe_key from varchar(64) to varchar(128).

Revision ID: 20260315_0011
Revises: 20260315_0010
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa

revision = "20260315_0011"
down_revision = "20260315_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "articles",
        "dedupe_key",
        existing_type=sa.String(64),
        type_=sa.String(128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "articles",
        "dedupe_key",
        existing_type=sa.String(128),
        type_=sa.String(64),
        existing_nullable=False,
    )
