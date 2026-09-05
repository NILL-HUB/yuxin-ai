"""add plan auto renew default

Revision ID: a8b9c0d1e2f4
Revises: b0c1d2e3f4a5
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a8b9c0d1e2f4'
down_revision = 'b0c1d2e3f4a5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('plan', sa.Column('auto_renew_default', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade():
    op.drop_column('plan', 'auto_renew_default')