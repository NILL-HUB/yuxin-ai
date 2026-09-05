"""add plan purchase limit columns

Revision ID: c5d6e7f8a9b1
Revises: d6e7f8a9b0c1
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b1'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('purchase_limit', sa.BigInteger(), server_default=sa.text('0'), nullable=False))
    op.add_column('plan', sa.Column('purchase_limit_period', sa.String(length=16), server_default=sa.text("'none'::character varying"), nullable=False))


def downgrade():
    op.drop_column('plan', 'purchase_limit_period')
    op.drop_column('plan', 'purchase_limit')