"""create agent_pool_config table

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-07-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'j6k7l8m9n0o1'
down_revision = 'i5j6k7l8m9n0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_pool_config',
        sa.Column('id', sa.UUID, nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('app_id', sa.UUID, nullable=False),
        sa.Column('primary_pool', sa.String(64), nullable=False, server_default=sa.text("'tenant'::character varying")),
        sa.Column('secondary_pools', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('risk_level', sa.String(32), nullable=False, server_default=sa.text("'medium'::character varying")),
        sa.Column('model_tier', sa.String(32), nullable=False, server_default=sa.text("'standard'::character varying")),
        sa.Column('model_id', sa.String(128), nullable=True),
        sa.Column('routing_priority', sa.Integer, nullable=False, server_default=sa.text('100')),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('health_status', sa.String(32), nullable=False, server_default=sa.text("'unknown'::character varying")),
        sa.Column('last_health_check_at', sa.DateTime, nullable=True),
        sa.Column('metadata', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.PrimaryKeyConstraint('id', name='pk_agent_pool_config_id'),
    )
    op.create_index('agent_pool_config_app_id_idx', 'agent_pool_config', ['app_id'])
    op.create_index('agent_pool_config_primary_pool_idx', 'agent_pool_config', ['primary_pool'])
    op.create_index('agent_pool_config_enabled_idx', 'agent_pool_config', ['enabled'])
    op.create_index('agent_pool_config_health_status_idx', 'agent_pool_config', ['health_status'])


def downgrade():
    op.drop_index('agent_pool_config_health_status_idx', table_name='agent_pool_config')
    op.drop_index('agent_pool_config_enabled_idx', table_name='agent_pool_config')
    op.drop_index('agent_pool_config_primary_pool_idx', table_name='agent_pool_config')
    op.drop_index('agent_pool_config_app_id_idx', table_name='agent_pool_config')
    op.drop_table('agent_pool_config')
