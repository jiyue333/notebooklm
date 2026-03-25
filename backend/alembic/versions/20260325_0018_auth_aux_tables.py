"""add auth auxiliary tables

Revision ID: 20260325_0018
Revises: 20260325_0017
Create Date: 2026-03-25 18:25:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql  # pragma: allowlist secret

revision = "20260325_0018"
down_revision = "20260325_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'password_reset_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),  # pragma: allowlist secret
        sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),  # pragma: allowlist secret
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'])
    op.create_index('uq_password_reset_tokens_token_hash', 'password_reset_tokens', ['token_hash'], unique=True)

    op.create_table(
        'oauth_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=False), primary_key=True, nullable=False),  # pragma: allowlist secret
        sa.Column('user_id', postgresql.UUID(as_uuid=False), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),  # pragma: allowlist secret
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('provider_user_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_oauth_accounts_user_id', 'oauth_accounts', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_oauth_accounts_user_id', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
    op.drop_index('uq_password_reset_tokens_token_hash', table_name='password_reset_tokens')
    op.drop_index('ix_password_reset_tokens_user_id', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
