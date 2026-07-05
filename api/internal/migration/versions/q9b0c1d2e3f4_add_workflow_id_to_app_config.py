"""add workflow_id to app_config

Revision ID: q9b0c1d2e3f4
Revises: p8a9b0c3e4f5
Create Date: 2026-07-05

为 app_config 表添加 workflow_id 字段，与 app_config_version 保持一致，
用于在发布 Workflow 类型应用时持久化运行时配置中绑定的 workflow_id。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'q9b0c1d2e3f4'
down_revision = 'p8a9b0c3e4f5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'app_config',
        sa.Column('workflow_id', sa.UUID(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('app_config', 'workflow_id')
