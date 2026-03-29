"""compat placeholder for missing historical revision

Revision ID: 20260328_0019
Revises: 20260325_0018
Create Date: 2026-03-28 23:59:00
"""

from __future__ import annotations

revision = "20260328_0019"
down_revision = "20260325_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op compatibility migration.

    Some environments were stamped to `20260328_0019` from an earlier branch.
    This placeholder keeps the revision graph contiguous so later migrations
    can be applied safely.
    """


def downgrade() -> None:
    """No-op compatibility migration."""

