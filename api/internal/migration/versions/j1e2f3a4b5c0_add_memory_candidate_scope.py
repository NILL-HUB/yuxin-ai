"""add memory_candidate.scope column

Revision ID: j1e2f3a4b5c0
Revises: i5d6e7f8a9b2
Create Date: 2026-06-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'j1e2f3a4b5c0'
down_revision = 'i5d6e7f8a9b2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'memory_candidate',
        sa.Column('scope', sa.String(length=64), server_default=sa.text("'global'::character varying"), nullable=False),
    )


def downgrade():
    op.drop_column('memory_candidate', 'scope')
