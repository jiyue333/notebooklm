"""fix embedding vectors to 1024 dimensions and create hnsw indexes

Revision ID: 20260309_0009
Revises: 20260309_0008
Create Date: 2026-03-09 23:20:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260309_0009"
down_revision = "20260309_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_article_vector")
    op.execute("DROP INDEX IF EXISTS ix_article_chunks_chunk_vector")
    op.execute(
        "UPDATE article_chunks SET chunk_vector = NULL "
        "WHERE chunk_vector IS NOT NULL AND vector_dims(chunk_vector) <> 1024"
    )
    op.execute(
        "UPDATE articles SET article_vector = NULL, embedding_dimension = NULL "
        "WHERE article_vector IS NOT NULL AND vector_dims(article_vector) <> 1024"
    )
    op.execute("ALTER TABLE article_chunks ALTER COLUMN chunk_vector TYPE vector(1024)")
    op.execute("ALTER TABLE articles ALTER COLUMN article_vector TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_articles_article_vector ON articles USING hnsw (article_vector vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_article_chunks_chunk_vector ON article_chunks USING hnsw (chunk_vector vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_article_chunks_chunk_vector")
    op.execute("DROP INDEX IF EXISTS ix_articles_article_vector")
    op.execute("ALTER TABLE article_chunks ALTER COLUMN chunk_vector TYPE vector")
    op.execute("ALTER TABLE articles ALTER COLUMN article_vector TYPE vector")
