"""add description column to model_pool_config

Revision ID: g2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g2b3c4d5e6f7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    # 使用 IF NOT EXISTS 保证幂等：description 列可能已通过临时 SQL 直接添加到现有库，
    # 此处对全新部署生效，对已存在该列的库为 no-op。
    op.execute(
        "ALTER TABLE model_pool_config "
        "ADD COLUMN IF NOT EXISTS description VARCHAR(512) NOT NULL DEFAULT ''"
    )


def downgrade():
    op.drop_column('model_pool_config', 'description')
