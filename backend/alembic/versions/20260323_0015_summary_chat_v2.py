"""summary chat v2: chunk contextualized_text, chunk_tsv, message metrics

Revision ID: 20260323_0015
Revises: 20260320_0014
Create Date: 2026-03-23 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260323_0015"
down_revision = "20260320_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── article_chunks ─────────────────────────────────────────────────
    op.add_column(
        "article_chunks",
        sa.Column("contextualized_text", sa.Text(), nullable=True, comment="上下文增强文本"),
    )
    op.execute(
        """
        ALTER TABLE article_chunks
        ADD COLUMN chunk_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(contextualized_text, chunk_text))
        ) STORED
        """
    )
    op.create_index(
        "ix_article_chunks_chunk_tsv",
        "article_chunks",
        ["chunk_tsv"],
        postgresql_using="gin",
    )
    op.execute("COMMENT ON COLUMN article_chunks.chunk_tsv IS '分块全文检索向量'")

    # ── conversation_messages ──────────────────────────────────────────
    op.add_column(
        "conversation_messages",
        sa.Column("web_searched", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="是否触发联网搜索"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("retrieval_count", sa.Integer(), nullable=True, comment="检索条数"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("citation_count", sa.Integer(), nullable=True, comment="引用条数"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("latency_ms", sa.Float(), nullable=True, comment="端到端延迟 ms"),
    )
    op.add_column(
        "conversation_messages",
        sa.Column("token_cost", sa.Integer(), nullable=True, comment="总 token 消耗"),
    )


def downgrade() -> None:
    op.drop_column("conversation_messages", "token_cost")
    op.drop_column("conversation_messages", "latency_ms")
    op.drop_column("conversation_messages", "citation_count")
    op.drop_column("conversation_messages", "retrieval_count")
    op.drop_column("conversation_messages", "web_searched")
    op.drop_index("ix_article_chunks_chunk_tsv", table_name="article_chunks")
    op.execute("ALTER TABLE article_chunks DROP COLUMN chunk_tsv")
    op.drop_column("article_chunks", "contextualized_text")
