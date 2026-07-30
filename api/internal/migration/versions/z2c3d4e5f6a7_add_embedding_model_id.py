# api/internal/migration/versions/z2c3d4e5f6a7_add_embedding_model_id.py
"""add embedding_model_id to knowledge_base and app_config

Revision ID: z2c3d4e5f6a7
Revises: y1b2c3d4e5f6
Create Date: 2026-07-18 14:45:00.000000

为 knowledge_base 和 app_config 表增加 embedding_model_id 字段，用于绑定
embedding 模型（FK → model_pool_config.id）。

- knowledge_base.embedding_model_id：知识库绑定的 embedding 模型，决定该知识库
  所有 segment 写入/检索时使用的维度
- app_config.embedding_model_id：Agent 绑定的 embedding 模型，决定该 Agent
  记忆系统（user_memory）写入/检索时使用的维度

为空时使用系统默认 embedding 模型（priority 最高的 active 模型）。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "z2c3d4e5f6a7"
down_revision = "y1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. knowledge_base 增加 embedding_model_id
    op.add_column(
        "knowledge_base",
        sa.Column("embedding_model_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_knowledge_base_embedding_model_id",
        "knowledge_base",
        "model_pool_config",
        ["embedding_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_knowledge_base_embedding_model_id",
        "knowledge_base",
        ["embedding_model_id"],
    )

    # 2. app_config 增加 embedding_model_id
    op.add_column(
        "app_config",
        sa.Column("embedding_model_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_app_config_embedding_model_id",
        "app_config",
        "model_pool_config",
        ["embedding_model_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_app_config_embedding_model_id",
        "app_config",
        ["embedding_model_id"],
    )

    # 3. app_config_version 增加 embedding_model_id（版本表同步字段）
    op.add_column(
        "app_config_version",
        sa.Column("embedding_model_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_app_config_version_embedding_model_id",
        "app_config_version",
        ["embedding_model_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_app_config_version_embedding_model_id", table_name="app_config_version"
    )
    op.drop_column("app_config_version", "embedding_model_id")

    op.drop_index("ix_app_config_embedding_model_id", table_name="app_config")
    op.drop_constraint(
        "fk_app_config_embedding_model_id", "app_config", type_="foreignkey"
    )
    op.drop_column("app_config", "embedding_model_id")

    op.drop_index("ix_knowledge_base_embedding_model_id", table_name="knowledge_base")
    op.drop_constraint(
        "fk_knowledge_base_embedding_model_id", "knowledge_base", type_="foreignkey"
    )
    op.drop_column("knowledge_base", "embedding_model_id")
