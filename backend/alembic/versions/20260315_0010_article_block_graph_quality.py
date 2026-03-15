"""Add block_graph_json and quality_profile_json to articles.

Revision ID: 20260315_0010
Revises: 20260309_0009
Create Date: 2026-03-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260315_0010"
down_revision = "20260309_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("block_graph_json", JSONB, nullable=True))
    op.add_column("articles", sa.Column("quality_profile_json", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "quality_profile_json")
    op.drop_column("articles", "block_graph_json")
