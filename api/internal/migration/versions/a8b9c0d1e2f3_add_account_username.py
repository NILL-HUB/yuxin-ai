"""add account username

Revision ID: a8b9c0d1e2f3
Revises: f7a8b9c0d1e2
Create Date: 2026-06-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8b9c0d1e2f3'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('account', sa.Column('username', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False))
    op.create_index('account_username_idx', 'account', ['username'])
    op.create_index('account_username_unique_idx', 'account', ['username'], unique=True, postgresql_where=sa.text("username <> ''"))


def downgrade():
    op.drop_index('account_username_unique_idx', table_name='account')
    op.drop_index('account_username_idx', table_name='account')
    op.drop_column('account', 'username')
