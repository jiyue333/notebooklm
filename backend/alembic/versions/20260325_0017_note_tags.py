"""add note tags json

Revision ID: 20260325_0017
Revises: 20260325_0016
Create Date: 2026-03-25 18:05:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260325_0017"
down_revision = "20260325_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('notes', sa.Column('tags_json', postgresql.JSONB(), nullable=True, comment='笔记标签 JSON'))  # pragma: allowlist secret


def downgrade() -> None:
    op.drop_column('notes', 'tags_json')
