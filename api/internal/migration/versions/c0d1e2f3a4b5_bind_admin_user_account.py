"""bind admin user account

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-06-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c0d1e2f3a4b5'
down_revision = 'b9c0d1e2f3a4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_user', sa.Column('account_id', sa.UUID(), nullable=True))
    op.create_index('admin_user_account_id_idx', 'admin_user', ['account_id'])
    op.create_foreign_key('fk_admin_user_account_id_account', 'admin_user', 'account', ['account_id'], ['id'])


def downgrade():
    op.drop_constraint('fk_admin_user_account_id_account', 'admin_user', type_='foreignkey')
    op.drop_index('admin_user_account_id_idx', table_name='admin_user')
    op.drop_column('admin_user', 'account_id')
