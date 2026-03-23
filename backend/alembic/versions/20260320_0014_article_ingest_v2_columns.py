"""add content_html, mdast_json, reading_time_minutes, tika_mime to articles

Revision ID: 20260320_0014
Revises: 20260318_0013
Create Date: 2026-03-20 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260320_0014"
down_revision = "20260318_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("content_html", sa.Text(), nullable=True, comment="remark 渲染的 HTML"))
    op.add_column("articles", sa.Column("mdast_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True, comment="mdast AST 树"))
    op.add_column("articles", sa.Column("tika_mime", sa.String(128), nullable=True, comment="Tika 检测的 MIME 类型"))
    op.add_column("articles", sa.Column("reading_time_minutes", sa.Integer(), nullable=True, comment="预估阅读时间(分钟)"))


def downgrade() -> None:
    op.drop_column("articles", "reading_time_minutes")
    op.drop_column("articles", "tika_mime")
    op.drop_column("articles", "mdast_json")
    op.drop_column("articles", "content_html")
