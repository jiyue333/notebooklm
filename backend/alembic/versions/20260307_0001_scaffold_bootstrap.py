"""bootstrap backend scaffold

Revision ID: 20260307_0001
Revises:
Create Date: 2026-03-07 00:00:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260307_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Step 1 only prepares the migration environment."""


def downgrade() -> None:
    """Step 1 only prepares the migration environment."""
