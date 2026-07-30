# api/internal/migration/versions/y1b2c3d4e5f6_add_embedding_dimension.py
"""add embedding_dimension to model_pool_config

Revision ID: y1b2c3d4e5f6
Revises: x1a2b3c4d5e6
Create Date: 2026-07-18 14:30:00.000000

为 model_pool_config 表增加 embedding_dimension 字段，用于存储 embedding 模型
的向量维度。仅 model_type='embedding' 的记录会使用此字段，其他类型记录保持 0/NULL。

维度信息由 admin 在创建/编辑 embedding 模型时通过下拉框选择（预设 768/1024/
1536/3072/4096 或自定义正整数）。运行时 EmbeddingsService 优先读取此字段，
内置字典作为兜底。

此字段是按维度分表存储架构（EmbeddingTableRouter）的配置基础。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "y1b2c3d4e5f6"
down_revision = "x1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增 embedding_dimension 字段（nullable，默认 0）
    op.add_column(
        "model_pool_config",
        sa.Column("embedding_dimension", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )

    # 2. 为现有 embedding 模型回填维度（基于 model_name 识别）
    # OpenAI 系列
    op.execute(
        "UPDATE model_pool_config SET embedding_dimension = 1536 "
        "WHERE model_type = 'embedding' AND embedding_dimension = 0 "
        "AND model_name IN ('text-embedding-3-small', 'text-embedding-ada-002')"
    )
    op.execute(
        "UPDATE model_pool_config SET embedding_dimension = 3072 "
        "WHERE model_type = 'embedding' AND embedding_dimension = 0 "
        "AND model_name = 'text-embedding-3-large'"
    )
    # SiliconFlow 系列
    op.execute(
        "UPDATE model_pool_config SET embedding_dimension = 4096 "
        "WHERE model_type = 'embedding' AND embedding_dimension = 0 "
        "AND model_name = 'Qwen/Qwen3-Embedding-8B'"
    )
    op.execute(
        "UPDATE model_pool_config SET embedding_dimension = 1024 "
        "WHERE model_type = 'embedding' AND embedding_dimension = 0 "
        "AND model_name IN ('BAAI/bge-large-zh-v1.5', 'BAAI/bge-m3', 'Pro/BAAI/bge-m3')"
    )
    op.execute(
        "UPDATE model_pool_config SET embedding_dimension = 768 "
        "WHERE model_type = 'embedding' AND embedding_dimension = 0 "
        "AND model_name = 'netease-youdao/bce-embedding-base_v1'"
    )

    # 3. 辅助索引：按 model_type + embedding_dimension 快速定位 embedding 模型
    op.create_index(
        "ix_model_pool_config_embedding_dim",
        "model_pool_config",
        ["model_type", "embedding_dimension"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_model_pool_config_embedding_dim", table_name="model_pool_config"
    )
    op.drop_column("model_pool_config", "embedding_dimension")
