"""add quota refresh mechanism

Revision ID: f2a3b4c5d6e7
Revises: c5d6e7f8a9b1
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2a3b4c5d6e7'
down_revision = 'c5d6e7f8a9b1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('quota_refresh_period', sa.String(length=16), server_default=sa.text("'none'::character varying"), nullable=False))
    op.add_column('credit_account', sa.Column('quota_granted', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.add_column('credit_account', sa.Column('quota_cycle_days', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.add_column('credit_account', sa.Column('quota_reset_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('credit_account', 'quota_reset_at')
    op.drop_column('credit_account', 'quota_cycle_days')
    op.drop_column('credit_account', 'quota_granted')
    op.drop_column('plan', 'quota_refresh_period')