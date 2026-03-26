"""add notebook tags and recent open timestamp

Revision ID: 20260325_0016
Revises: 20260323_0015
Create Date: 2026-03-25 17:30:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260325_0016"
down_revision = "20260323_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'notebooks',
        sa.Column('tags_json', postgresql.JSONB(), nullable=True, comment='笔记本标签 JSON'),  # pragma: allowlist secret
    )
    op.add_column(
        'notebooks',
        sa.Column('last_opened_at', sa.DateTime(timezone=True), nullable=True, comment='最近打开时间'),
    )


def downgrade() -> None:
    op.drop_column('notebooks', 'last_opened_at')
    op.drop_column('notebooks', 'tags_json')
