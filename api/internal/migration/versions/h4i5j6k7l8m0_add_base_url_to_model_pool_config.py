"""add base_url column to model_pool_config

Revision ID: h4i5j6k7l8m0
Revises: g3b4c5d6e7f9
Create Date: 2026-07-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'h4i5j6k7l8m0'
down_revision = 'k2f3a4b5c6d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_pool_config',
        sa.Column('base_url', sa.String(length=512), nullable=True),
    )


def downgrade():
    op.drop_column('model_pool_config', 'base_url')
