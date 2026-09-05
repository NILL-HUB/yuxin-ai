"""add plan soft delete

Revision ID: b0c1d2e3f4a5
Revises: f2a3b4c5d6e7
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b0c1d2e3f4a5'
down_revision = 'f2a3b4c5d6e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('deleted_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('plan', 'deleted_at')