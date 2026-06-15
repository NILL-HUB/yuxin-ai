"""add credit transaction idempotent index

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op


revision = 'd5e6f7a8b9c0'
down_revision = 'c4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        'credit_transaction_source_type_unique_idx',
        'credit_transaction',
        ['source', 'source_id', 'transaction_type'],
        unique=True,
    )


def downgrade():
    op.drop_index('credit_transaction_source_type_unique_idx', table_name='credit_transaction')
