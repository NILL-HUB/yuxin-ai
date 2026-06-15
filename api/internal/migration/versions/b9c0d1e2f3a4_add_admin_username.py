"""add admin username

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-06-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b9c0d1e2f3a4'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('admin_user', sa.Column('username', sa.String(length=64), nullable=False, server_default=''))
    op.execute("UPDATE admin_user SET username = lower(split_part(email, '@', 1)) WHERE username = '' AND email IS NOT NULL AND email <> ''")
    op.execute("UPDATE admin_user SET username = 'admin_' || substring(id::text, 1, 8) WHERE username = ''")
    op.alter_column('admin_user', 'email', existing_type=sa.String(length=255), nullable=True)
    op.create_unique_constraint('uq_admin_user_username', 'admin_user', ['username'])
    op.create_index('admin_user_username_idx', 'admin_user', ['username'])


def downgrade():
    op.drop_index('admin_user_username_idx', table_name='admin_user')
    op.drop_constraint('uq_admin_user_username', 'admin_user', type_='unique')
    op.alter_column('admin_user', 'email', existing_type=sa.String(length=255), nullable=False)
    op.drop_column('admin_user', 'username')
