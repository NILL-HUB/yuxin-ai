"""add model cost base columns (cost price per 1k tokens)

Revision ID: d7e8f9a0b1c2
Revises: d6e7f8a9b0c2
Create Date: 2026-08-30 00:00:00.000000

存量数据策略：成本基准默认等于销售定价（cost = price），
避免迁移后毛利为负，运营后续逐模型校准。
"""
from alembic import op
import sqlalchemy as sa


revision = 'd7e8f9a0b1c2'
down_revision = 'd6e7f8a9b0c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'model_pool_config',
        sa.Column('input_cost_per_1k_tokens', sa.Numeric(precision=12, scale=6),
                  server_default=sa.text('0.000000'), nullable=False),
    )
    op.add_column(
        'model_pool_config',
        sa.Column('output_cost_per_1k_tokens', sa.Numeric(precision=12, scale=6),
                  server_default=sa.text('0.000000'), nullable=False),
    )
    # 存量成本 = 售价（单位统一为 算力/1k token；成本折算靠 credits_per_yuan）
    op.execute("""
        UPDATE model_pool_config
        SET input_cost_per_1k_tokens = input_price_per_1k_tokens,
            output_cost_per_1k_tokens = output_price_per_1k_tokens
    """)


def downgrade():
    op.drop_column('model_pool_config', 'output_cost_per_1k_tokens')
    op.drop_column('model_pool_config', 'input_cost_per_1k_tokens')