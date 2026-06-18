"""add last_error to external_data_source

Revision ID: d1e2f3a4b5d5
Revises: d1e2f3a4b5d4
Create Date: 2026-06-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5d5'
down_revision = 'd1e2f3a4b5d4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('external_data_source', sa.Column('last_error', sa.Text(), nullable=False, server_default=sa.text("''::text")))


def downgrade():
    op.drop_column('external_data_source', 'last_error')
