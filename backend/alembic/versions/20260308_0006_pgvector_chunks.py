"""add pgvector columns and article chunks

Revision ID: 20260308_0006
Revises: 20260308_0005
Create Date: 2026-03-08 02:00:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260308_0006"
down_revision = "20260308_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE articles ADD COLUMN article_vector vector(3072)")
    op.execute(
        """
        CREATE TABLE article_chunks (
            id uuid PRIMARY KEY,
            article_id uuid NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            section_path text NULL,
            heading_title text NULL,
            token_count integer NOT NULL,
            chunk_text text NOT NULL,
            chunk_vector vector(3072) NULL,
            created_at timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX ix_article_chunks_article_id ON article_chunks(article_id)")
    op.execute(
        "CREATE INDEX ix_articles_article_vector ON articles USING hnsw (article_vector vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_article_chunks_chunk_vector ON article_chunks USING hnsw (chunk_vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_article_chunks_chunk_vector")
    op.execute("DROP INDEX IF EXISTS ix_articles_article_vector")
    op.execute("DROP INDEX IF EXISTS ix_article_chunks_article_id")
    op.execute("DROP TABLE IF EXISTS article_chunks")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS article_vector")
