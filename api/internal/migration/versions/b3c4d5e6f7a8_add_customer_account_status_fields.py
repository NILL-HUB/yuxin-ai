"""add customer account status fields

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('account', sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False))
    op.add_column('account', sa.Column('disabled_at', sa.DateTime(), nullable=True))
    op.add_column('account', sa.Column('disabled_by', sa.UUID(), nullable=True))
    op.add_column('account', sa.Column('disabled_reason', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False))
    op.create_index('account_status_idx', 'account', ['status'])


def downgrade():
    op.drop_index('account_status_idx', table_name='account')
    op.drop_column('account', 'disabled_reason')
    op.drop_column('account', 'disabled_by')
    op.drop_column('account', 'disabled_at')
    op.drop_column('account', 'status')
