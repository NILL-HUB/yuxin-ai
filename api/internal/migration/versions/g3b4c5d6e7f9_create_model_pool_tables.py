"""create model pool tables

Revision ID: g3b4c5d6e7f9
Revises: f2a3b4c5d6e8
Create Date: 2026-06-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'g3b4c5d6e7f9'
down_revision = 'f2a3b4c5d6e8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'model_pool_config',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('provider', sa.String(length=128), nullable=False),
        sa.Column('model_name', sa.String(length=255), nullable=False),
        sa.Column('display_name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('tier', sa.String(length=64), server_default=sa.text("'standard'::character varying"), nullable=False),
        sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('price_per_1k_tokens', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False),
        sa.Column('max_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('fallback_model_id', sa.String(length=36), nullable=True),
        sa.Column('priority', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_model_pool_config_id'),
    )
    op.create_index('model_pool_config_provider_idx', 'model_pool_config', ['provider'])
    op.create_index('model_pool_config_status_idx', 'model_pool_config', ['status'])
    op.create_index('model_pool_config_tier_idx', 'model_pool_config', ['tier'])

    op.create_table(
        'model_key_config',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('provider', sa.String(length=128), nullable=False),
        sa.Column('key_alias', sa.String(length=255), nullable=False),
        sa.Column('key_value_encrypted', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('tenant_quota', sa.Numeric(precision=12, scale=4), server_default=sa.text('0.0000'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('failure_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('used_credits', sa.Numeric(precision=12, scale=4), server_default=sa.text('0.0000'), nullable=False),
        sa.Column('model_id', sa.String(length=36), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_model_key_config_id'),
    )
    op.create_index('model_key_config_provider_idx', 'model_key_config', ['provider'])
    op.create_index('model_key_config_status_idx', 'model_key_config', ['status'])
    op.create_index('model_key_config_model_id_idx', 'model_key_config', ['model_id'])
    op.create_index('model_key_config_expires_at_idx', 'model_key_config', ['expires_at'])

    op.create_table(
        'model_tier_policy',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tier_code', sa.String(length=64), nullable=False),
        sa.Column('allowed_models', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('default_model', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('routing_rules', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_model_tier_policy_id'),
    )
    op.create_index('model_tier_policy_code_idx', 'model_tier_policy', ['tier_code'], unique=True)

    op.create_table(
        'cost_policy',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('policy_name', sa.String(length=255), nullable=False),
        sa.Column('model_tier', sa.String(length=64), server_default=sa.text("'standard'::character varying"), nullable=False),
        sa.Column('max_cost_per_request', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False),
        sa.Column('billing_mode', sa.String(length=64), server_default=sa.text("'token'::character varying"), nullable=False),
        sa.Column('upgrade_threshold', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_cost_policy_id'),
    )
    op.create_index('cost_policy_name_idx', 'cost_policy', ['policy_name'], unique=True)
    op.create_index('cost_policy_tier_idx', 'cost_policy', ['model_tier'])


def downgrade():
    op.drop_index('cost_policy_tier_idx', table_name='cost_policy')
    op.drop_index('cost_policy_name_idx', table_name='cost_policy')
    op.drop_table('cost_policy')

    op.drop_index('model_tier_policy_code_idx', table_name='model_tier_policy')
    op.drop_table('model_tier_policy')

    op.drop_index('model_key_config_expires_at_idx', table_name='model_key_config')
    op.drop_index('model_key_config_model_id_idx', table_name='model_key_config')
    op.drop_index('model_key_config_status_idx', table_name='model_key_config')
    op.drop_index('model_key_config_provider_idx', table_name='model_key_config')
    op.drop_table('model_key_config')

    op.drop_index('model_pool_config_tier_idx', table_name='model_pool_config')
    op.drop_index('model_pool_config_status_idx', table_name='model_pool_config')
    op.drop_index('model_pool_config_provider_idx', table_name='model_pool_config')
    op.drop_table('model_pool_config')
