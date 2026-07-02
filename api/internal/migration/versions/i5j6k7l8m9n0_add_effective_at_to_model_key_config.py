"""add effective_at column to model_key_config

Revision ID: i5j6k7l8m9n0
Revises: h4i5j6k7l8m0
Create Date: 2026-07-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'i5j6k7l8m9n0'
down_revision = 'h4i5j6k7l8m0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_key_config',
        sa.Column('effective_at', sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column('model_key_config', 'effective_at')
