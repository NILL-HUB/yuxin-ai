# api/internal/migration/versions/c7d8e9f0a1b2_add_model_type_to_public_ai_feature_config.py
"""add model_type to public_ai_feature_config

Revision ID: c7d8e9f0a1b2
Revises: c6d7e8f9a0b1
Create Date: 2026-07-22 13:00:00.000000

为公共 AI 功能配置加 model_type 字段，标识功能需要的模型类型。
降级路径和后台模型选择均按 model_type 过滤，防止 image 类功能误匹配 chat 模型。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 加列，默认 'chat'
    op.add_column(
        "public_ai_feature_config",
        sa.Column(
            "model_type",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'chat'::character varying"),
        ),
    )
    op.create_index(
        "ix_public_ai_feature_model_type",
        "public_ai_feature_config",
        ["model_type"],
    )

    # 2. 更新 icon_image_generation 为 image 类型
    op.get_bind().execute(
        sa.text(
            "UPDATE public_ai_feature_config SET model_type = 'image' "
            "WHERE feature_key = 'icon_image_generation'"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_public_ai_feature_model_type", table_name="public_ai_feature_config")
    op.drop_column("public_ai_feature_config", "model_type")
