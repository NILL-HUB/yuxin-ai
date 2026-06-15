"""add redeem code batch status

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-06-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('redeem_code_batch', sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False))
    op.add_column('redeem_code_batch', sa.Column('disabled_at', sa.DateTime(), nullable=True))
    op.create_index('redeem_code_batch_only_status_idx', 'redeem_code_batch', ['status'])


def downgrade():
    op.drop_index('redeem_code_batch_only_status_idx', table_name='redeem_code_batch')
    op.drop_column('redeem_code_batch', 'disabled_at')
    op.drop_column('redeem_code_batch', 'status')
