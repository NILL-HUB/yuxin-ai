"""add app assignment

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'app_assignment',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('app_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('assigned_by', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.ForeignKeyConstraint(['app_id'], ['app.id']),
        sa.ForeignKeyConstraint(['assigned_by'], ['admin_user.id']),
        sa.PrimaryKeyConstraint('id', name='pk_app_assignment_id'),
    )
    op.create_index('app_assignment_app_account_unique_idx', 'app_assignment', ['app_id', 'account_id'], unique=True)
    op.create_index('app_assignment_account_status_idx', 'app_assignment', ['account_id', 'status'], unique=False)
    op.create_index('app_assignment_app_status_idx', 'app_assignment', ['app_id', 'status'], unique=False)


def downgrade():
    op.drop_index('app_assignment_app_status_idx', table_name='app_assignment')
    op.drop_index('app_assignment_account_status_idx', table_name='app_assignment')
    op.drop_index('app_assignment_app_account_unique_idx', table_name='app_assignment')
    op.drop_table('app_assignment')
