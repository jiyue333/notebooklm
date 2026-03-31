"""add article highlights

Revision ID: 20260329_0023
Revises: 20260329_0022
Create Date: 2026-03-28 19:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260329_0023"
down_revision = "20260329_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_highlights",
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=False, comment="所属用户 ID"),  # pragma: allowlist secret
        sa.Column("notebook_id", postgresql.UUID(as_uuid=False), nullable=False, comment="所属笔记本 ID"),  # pragma: allowlist secret
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=False, comment="所属文章 ID"),  # pragma: allowlist secret
        sa.Column("selected_text", sa.Text(), nullable=False, comment="高亮文本"),
        sa.Column("color", sa.String(length=24), nullable=False, server_default=sa.text("'yellow'"), comment="高亮颜色"),
        sa.Column("comment_text", sa.Text(), nullable=True, comment="批注内容"),
        sa.Column("start_offset", sa.Integer(), nullable=True, comment="正文字符起始偏移"),
        sa.Column("end_offset", sa.Integer(), nullable=True, comment="正文字符结束偏移"),
        sa.Column("occurrence_index", sa.Integer(), nullable=True, comment="同文本出现序号(0-based)"),
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False, comment="主键 ID"),  # pragma: allowlist secret
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE", name=op.f("fk_article_highlights_article_id_articles")),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE", name=op.f("fk_article_highlights_notebook_id_notebooks")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=op.f("fk_article_highlights_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_article_highlights")),
        comment="文章高亮与批注",
    )
    op.create_index(op.f("ix_article_highlights_article_id"), "article_highlights", ["article_id"], unique=False)
    op.create_index(op.f("ix_article_highlights_notebook_id"), "article_highlights", ["notebook_id"], unique=False)
    op.create_index(op.f("ix_article_highlights_user_id"), "article_highlights", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_article_highlights_user_id"), table_name="article_highlights")
    op.drop_index(op.f("ix_article_highlights_notebook_id"), table_name="article_highlights")
    op.drop_index(op.f("ix_article_highlights_article_id"), table_name="article_highlights")
    op.drop_table("article_highlights")
