# api/internal/migration/versions/a4b5c6d7e8f9_create_public_ai_feature_config.py
"""create public_ai_feature_config table

Revision ID: a4b5c6d7e8f9
Revises: a3d4e5f6g7b8
Create Date: 2026-07-20 10:00:00.000000

新建公共 AI 功能配置表，用于管理平台侧发起的、用户不承担成本的 AI 调用
（图标生成、记忆巩固、意图识别等）所使用的模型配置。
每个 feature_key 独立配置一个 model_pool_config 中的模型。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "a4b5c6d7e8f9"
down_revision = "a3d4e5f6g7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_ai_feature_config",
        sa.Column("feature_key", sa.String(length=64), nullable=False),
        sa.Column("feature_name", sa.String(length=128), nullable=False),
        sa.Column("feature_category", sa.String(length=64), nullable=False, server_default=sa.text("'general'::character varying")),
        sa.Column("feature_description", sa.String(length=512), nullable=True),
        sa.Column("model_config_id", sa.UUID(), nullable=True),
        sa.Column("provider_credential_key", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("fallback_tier", sa.String(length=64), nullable=False, server_default=sa.text("'cheap'::character varying")),
        sa.Column("extra_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("feature_key", name="pk_public_ai_feature_config_feature_key"),
        sa.ForeignKeyConstraint(["model_config_id"], ["model_pool_config.id"], name="fk_public_ai_feature_model_config_id", ondelete="SET NULL"),
    )
    op.create_index("ix_public_ai_feature_category", "public_ai_feature_config", ["feature_category"])
    op.create_index("ix_public_ai_feature_enabled", "public_ai_feature_config", ["enabled"])


def downgrade() -> None:
    op.drop_index("ix_public_ai_feature_enabled", table_name="public_ai_feature_config")
    op.drop_index("ix_public_ai_feature_category", table_name="public_ai_feature_config")
    op.drop_table("public_ai_feature_config")
