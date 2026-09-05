"""add plan auto_renew_threshold_days

Revision ID: d6e7f8a9b0c1
Revises: e0f1a2b3c4d8
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd6e7f8a9b0c1'
down_revision = 'e0f1a2b3c4d8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('auto_renew_threshold_days', sa.BigInteger(), server_default=sa.text('1'), nullable=False))


def downgrade():
    op.drop_column('plan', 'auto_renew_threshold_days')