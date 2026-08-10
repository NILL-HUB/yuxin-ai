"""split model_pool_config max_tokens into max_input_tokens + max_output_tokens

Revision ID: d2e3f4a5b6c0
Revises: m8b9c0d1e2f3
Create Date: 2026-08-05 00:00:00.000000

将模型池的单一 max_tokens（总上下文窗口）拆分为：
- max_input_tokens：最大输入长度（prompt/context 上限）
- max_output_tokens：最大输出长度（生成内容上限）

保留 max_tokens 列作为历史兼容字段；存量数据回填为 max_tokens，
保证拆分后行为不劣化，再由管理端按模型能力分别调整。
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c0"
down_revision = "m8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "model_pool_config",
        sa.Column(
            "max_input_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "model_pool_config",
        sa.Column(
            "max_output_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    # 存量数据回填：输入窗口沿用历史 max_tokens，输出上限沿用 max_tokens（行为不变，之后可单独调整）
    op.execute(
        """
        UPDATE model_pool_config
        SET max_input_tokens = max_tokens,
            max_output_tokens = max_tokens
        WHERE max_input_tokens = 0 AND max_output_tokens = 0
        """
    )


def downgrade():
    op.drop_column("model_pool_config", "max_output_tokens")
    op.drop_column("model_pool_config", "max_input_tokens")
