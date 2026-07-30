"""drop agent_pool_config routing fields

Revision ID: i4d5e6f7a8b9
Revises: h3c4d5e6f7a8
Create Date: 2026-07-30 03:00:00.000000

变更内容：
删除 agent_pool_config 表中已被 agent_metadata 替代的 6 个路由死字段：
- primary_pool（部署范围，路由不消费，实际读 agent_metadata.primary_pool）
- secondary_pools（同上）
- risk_level（同上）
- model_tier（同上）
- model_id（同上，且未进入候选序列化）
- routing_priority（同上）

同时删除 primary_pool 字段的索引 agent_pool_config_primary_pool_idx。

路由逻辑已统一由 App.agent_metadata 承载，AgentPoolConfig 仅保留部署/健康/元数据。

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'i4d5e6f7a8b9'
down_revision = 'h3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 删除 primary_pool 索引
    op.drop_index('agent_pool_config_primary_pool_idx', table_name='agent_pool_config')

    # 2. 删除 6 个路由死字段
    op.drop_column('agent_pool_config', 'routing_priority')
    op.drop_column('agent_pool_config', 'model_id')
    op.drop_column('agent_pool_config', 'model_tier')
    op.drop_column('agent_pool_config', 'risk_level')
    op.drop_column('agent_pool_config', 'secondary_pools')
    op.drop_column('agent_pool_config', 'primary_pool')


def downgrade():
    # 回滚：重建 6 个字段 + 索引
    op.add_column('agent_pool_config',
        sa.Column('primary_pool', sa.String(64), nullable=False, server_default=sa.text("'tenant'::character varying")))
    op.add_column('agent_pool_config',
        sa.Column('secondary_pools', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('agent_pool_config',
        sa.Column('risk_level', sa.String(32), nullable=False, server_default=sa.text("'medium'::character varying")))
    op.add_column('agent_pool_config',
        sa.Column('model_tier', sa.String(32), nullable=False, server_default=sa.text("'2'::character varying")))
    op.add_column('agent_pool_config',
        sa.Column('model_id', sa.String(128), nullable=True))
    op.add_column('agent_pool_config',
        sa.Column('routing_priority', sa.Integer(), nullable=False, server_default=sa.text("100")))

    op.create_index('agent_pool_config_primary_pool_idx', 'agent_pool_config', ['primary_pool'])
