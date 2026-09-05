"""add billing config table and model io pricing

Revision ID: d6e7f8a9b0c2
Revises: c3d4e5f6a7b9
Create Date: 2026-08-29 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd6e7f8a9b0c2'
down_revision = 'c3d4e5f6a7b9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'billing_config',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('code', sa.String(length=64), nullable=False),
        sa.Column('value_numeric', sa.Numeric(precision=12, scale=6), server_default=sa.text('0'), nullable=False),
        sa.Column('description', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_billing_config_id'),
    )
    op.create_index('billing_config_code_idx', 'billing_config', ['code'], unique=True)
    op.add_column('model_pool_config', sa.Column('input_price_per_1k_tokens', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False))
    op.add_column('model_pool_config', sa.Column('output_price_per_1k_tokens', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False))


def downgrade():
    op.drop_column('model_pool_config', 'output_price_per_1k_tokens')
    op.drop_column('model_pool_config', 'input_price_per_1k_tokens')
    op.drop_index('billing_config_code_idx', table_name='billing_config')
    op.drop_table('billing_config')