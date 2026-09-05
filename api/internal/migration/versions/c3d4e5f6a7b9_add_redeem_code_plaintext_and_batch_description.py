"""add redeem code plaintext storage and batch description

Revision ID: c3d4e5f6a7b9
Revises: a8b9c0d1e2f4
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b9'
down_revision = 'a8b9c0d1e2f4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('redeem_code', sa.Column('code_encrypted', sa.String(length=1024), nullable=True))
    op.add_column('redeem_code_batch', sa.Column('description', sa.String(length=500), server_default=sa.text("''::character varying"), nullable=False))


def downgrade():
    op.drop_column('redeem_code_batch', 'description')
    op.drop_column('redeem_code', 'code_encrypted')