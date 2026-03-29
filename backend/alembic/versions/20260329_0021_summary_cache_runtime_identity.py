"""Fix summary cache identity to include runtime dimensions.

Revision ID: 20260329_0021
Revises: 20260329_0020
Create Date: 2026-03-29

"""

from __future__ import annotations

from alembic import op

revision = "20260329_0021"
down_revision = "20260329_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_summary_caches_identity", "summary_caches", type_="unique")
    op.create_unique_constraint(
        "uq_summary_caches_runtime_identity",
        "summary_caches",
        [
            "article_id",
            "content_hash",
            "prompt_version",
            "model_provider",
            "model_name",
            "output_language",
        ],
    )


def downgrade() -> None:
    op.drop_constraint("uq_summary_caches_runtime_identity", "summary_caches", type_="unique")
    op.create_unique_constraint(
        "uq_summary_caches_identity",
        "summary_caches",
        ["article_id", "content_hash", "prompt_version"],
    )
