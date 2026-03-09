"""add embedding runtime keys and flexible vector metadata

Revision ID: 20260309_0008
Revises: 20260309_0007
Create Date: 2026-03-09 18:10:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260309_0008"
down_revision = "20260309_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("embedding_api_key_ciphertext", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("embedding_api_key_last4", sa.String(length=4), nullable=True))
    op.add_column("users", sa.Column("embedding_api_key_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("articles", sa.Column("embedding_provider", sa.String(length=64), nullable=True))
    op.add_column("articles", sa.Column("embedding_model", sa.String(length=128), nullable=True))
    op.add_column("articles", sa.Column("embedding_profile_key", sa.String(length=64), nullable=True))
    op.add_column("articles", sa.Column("embedding_dimension", sa.Integer(), nullable=True))
    op.create_index("ix_articles_embedding_profile_key", "articles", ["embedding_profile_key"], unique=False)

    op.execute("DROP INDEX IF EXISTS ix_articles_article_vector")
    op.execute("DROP INDEX IF EXISTS ix_article_chunks_chunk_vector")
    op.execute("ALTER TABLE articles ALTER COLUMN article_vector TYPE vector")
    op.execute("ALTER TABLE article_chunks ALTER COLUMN chunk_vector TYPE vector")


def downgrade() -> None:
    op.execute(
        "UPDATE article_chunks SET chunk_vector = NULL "
        "WHERE chunk_vector IS NOT NULL AND vector_dims(chunk_vector) <> 3072"
    )
    op.execute(
        "UPDATE articles SET article_vector = NULL "
        "WHERE article_vector IS NOT NULL AND vector_dims(article_vector) <> 3072"
    )
    op.execute("ALTER TABLE article_chunks ALTER COLUMN chunk_vector TYPE vector(3072)")
    op.execute("ALTER TABLE articles ALTER COLUMN article_vector TYPE vector(3072)")
    op.execute(
        "CREATE INDEX ix_articles_article_vector ON articles USING hnsw (article_vector vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_article_chunks_chunk_vector ON article_chunks USING hnsw (chunk_vector vector_cosine_ops)"
    )

    op.drop_index("ix_articles_embedding_profile_key", table_name="articles")
    op.drop_column("articles", "embedding_dimension")
    op.drop_column("articles", "embedding_profile_key")
    op.drop_column("articles", "embedding_model")
    op.drop_column("articles", "embedding_provider")

    op.drop_column("users", "embedding_api_key_updated_at")
    op.drop_column("users", "embedding_api_key_last4")
    op.drop_column("users", "embedding_api_key_ciphertext")
