"""widen balance transaction idempotency to account level

Revision ID: e0f1a2b3c4d8
Revises: fe1a2b3c4d5e
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op


revision = 'e0f1a2b3c4d8'
down_revision = 'fe1a2b3c4d5e'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index('uq_balance_transaction_source_type', table_name='balance_transaction')
    op.create_index(
        'uq_balance_transaction_account_source_type',
        'balance_transaction',
        ['account_id', 'source', 'source_id', 'amount_type'],
        unique=True,
    )


def downgrade():
    op.drop_index('uq_balance_transaction_account_source_type', table_name='balance_transaction')
    op.create_index(
        'uq_balance_transaction_source_type',
        'balance_transaction',
        ['source', 'source_id', 'amount_type'],
        unique=True,
    )