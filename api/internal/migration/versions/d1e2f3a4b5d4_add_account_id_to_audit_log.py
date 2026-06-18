"""add account_id to audit_log

Revision ID: d1e2f3a4b5d4
Revises: d1e2f3a4b5d3
Create Date: 2026-06-18 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5d4'
down_revision = 'd1e2f3a4b5d3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('audit_log', sa.Column('account_id', sa.UUID(), nullable=True))
    op.create_index('audit_log_account_id_idx', 'audit_log', ['account_id'])
    op.create_foreign_key(
        'fk_audit_log_account_id_account',
        'audit_log',
        'account',
        ['account_id'],
        ['id'],
    )


def downgrade():
    op.drop_constraint('fk_audit_log_account_id_account', 'audit_log', type_='foreignkey')
    op.drop_index('audit_log_account_id_idx', table_name='audit_log')
    op.drop_column('audit_log', 'account_id')
