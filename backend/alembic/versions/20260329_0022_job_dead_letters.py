"""Add dead-letter queue table for async jobs.

Revision ID: 20260329_0022
Revises: 20260329_0021
Create Date: 2026-03-29

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260329_0022"
down_revision = "20260329_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_dead_letters",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=False), nullable=False, comment="原任务 ID"),
        sa.Column("job_type", sa.String(length=64), nullable=False, comment="任务类型"),
        sa.Column("article_id", postgresql.UUID(as_uuid=False), nullable=True, comment="关联文章 ID"),
        sa.Column("search_session_id", postgresql.UUID(as_uuid=False), nullable=True, comment="关联搜索会话 ID"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False, comment="去重键"),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_error", sa.Text(), nullable=True, comment="最终错误信息"),
        sa.Column("error_code", sa.String(length=64), nullable=True, comment="错误代码"),
        sa.Column("dead_reason", sa.String(length=64), nullable=False, server_default="attempts_exhausted", comment="死信原因"),
        sa.Column("replay_count", sa.Integer(), nullable=False, server_default="0", comment="重投次数"),
        sa.Column("last_replay_job_id", postgresql.UUID(as_uuid=False), nullable=True, comment="最近一次重投任务 ID"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, comment="原任务创建时间"),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=False, comment="进入死信时间"),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True, comment="最近一次重投时间"),
        comment="任务死信队列表",
    )
    op.create_unique_constraint("uq_job_dead_letters_job_id", "job_dead_letters", ["job_id"])
    op.create_index("ix_job_dead_letters_job_id", "job_dead_letters", ["job_id"], unique=False)
    op.create_index("ix_job_dead_letters_article_id", "job_dead_letters", ["article_id"], unique=False)
    op.create_index("ix_job_dead_letters_search_session_id", "job_dead_letters", ["search_session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_dead_letters_search_session_id", table_name="job_dead_letters")
    op.drop_index("ix_job_dead_letters_article_id", table_name="job_dead_letters")
    op.drop_index("ix_job_dead_letters_job_id", table_name="job_dead_letters")
    op.drop_constraint("uq_job_dead_letters_job_id", "job_dead_letters", type_="unique")
    op.drop_table("job_dead_letters")
