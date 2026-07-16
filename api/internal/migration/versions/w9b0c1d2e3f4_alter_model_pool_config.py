# api/internal/migration/versions/w9b0c1d2e3f4_alter_model_pool_config.py
"""alter model_pool_config: add model_type/compatible_api, drop base_url

Revision ID: w9b0c1d2e3f4
Revises: v8a9b0c1d2e3
Create Date: 2026-07-16 23:03:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "w9b0c1d2e3f4"
down_revision = "v8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增字段（nullable）
    op.add_column("model_pool_config", sa.Column("model_type", sa.String(length=32), nullable=True))
    op.add_column("model_pool_config", sa.Column("compatible_api", sa.String(length=32), nullable=True))

    # 2. 回填默认值
    op.execute("UPDATE model_pool_config SET model_type = 'chat' WHERE model_type IS NULL")
    op.execute("UPDATE model_pool_config SET compatible_api = 'openai' WHERE compatible_api IS NULL")

    # 3. 设为 NOT NULL
    op.alter_column("model_pool_config", "model_type", existing_type=sa.String(length=32), nullable=False, server_default=sa.text("'chat'::character varying"))
    op.alter_column("model_pool_config", "compatible_api", existing_type=sa.String(length=32), nullable=False, server_default=sa.text("'openai'::character varying"))

    # 4. 新增索引
    op.create_index("ix_model_pool_config_provider_model", "model_pool_config", ["provider", "model_name"])
    op.create_index("ix_model_pool_config_model_type", "model_pool_config", ["model_type"])

    # 5. 删除 base_url 列
    op.drop_column("model_pool_config", "base_url")


def downgrade() -> None:
    # 恢复 base_url 列
    op.add_column("model_pool_config", sa.Column("base_url", sa.String(length=512), nullable=True))

    # 删除索引
    op.drop_index("ix_model_pool_config_model_type", table_name="model_pool_config")
    op.drop_index("ix_model_pool_config_provider_model", table_name="model_pool_config")

    # 删除字段
    op.drop_column("model_pool_config", "compatible_api")
    op.drop_column("model_pool_config", "model_type")
