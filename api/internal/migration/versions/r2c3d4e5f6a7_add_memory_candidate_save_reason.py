"""add memory_candidate.save_reason column

Revision ID: r2c3d4e5f6a7
Revises: q9b0c1d2e3f4
Create Date: 2026-07-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'r2c3d4e5f6a7'
down_revision = 'q9b0c1d2e3f4'
branch_labels = None
depends_on = None


def upgrade():
    # 新增 save_reason 列，用于存储候选记忆的保存理由
    op.add_column(
        'memory_candidate',
        sa.Column('save_reason', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column('memory_candidate', 'save_reason')
