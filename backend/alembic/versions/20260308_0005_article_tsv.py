"""add article tsvector column

Revision ID: 20260308_0005
Revises: 20260308_0004
Create Date: 2026-03-08 01:30:00
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260308_0005"
down_revision = "20260308_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE articles
        ADD COLUMN article_tsv tsvector GENERATED ALWAYS AS (
            setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('simple', coalesce(article_retrieval_text, '')), 'B')
        ) STORED
        """
    )
    op.execute(
        """
        UPDATE articles
        SET article_retrieval_text = COALESCE(
            article_retrieval_text,
            concat_ws(E'\\n\\n', title, clean_markdown, preview_markdown)
        )
        """
    )
    op.execute("CREATE INDEX ix_articles_article_tsv ON articles USING gin(article_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_articles_article_tsv")
    op.execute("ALTER TABLE articles DROP COLUMN IF EXISTS article_tsv")
