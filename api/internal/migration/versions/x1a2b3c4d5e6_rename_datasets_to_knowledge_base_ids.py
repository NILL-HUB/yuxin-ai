# api/internal/migration/versions/x1a2b3c4d5e6_rename_datasets_to_knowledge_base_ids.py
"""rename datasets to knowledge_base_ids in app_config/app_config_version

Revision ID: x1a2b3c4d5e6
Revises: w9b0c1d2e3f4
Create Date: 2026-07-17 00:35:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "x1a2b3c4d5e6"
down_revision = "w9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """将 app_config_version.datasets 重命名为 knowledge_base_ids，并为 app_config 添加 knowledge_base_ids"""
    # 1. app_config_version 表：将 datasets 列改名为 knowledge_base_ids
    op.alter_column(
        "app_config_version",
        "datasets",
        new_column_name="knowledge_base_ids",
        existing_type=JSONB(astext_type=sa.Text()),
        existing_server_default=sa.text("'[]'::jsonb"),
        existing_nullable=False,
    )

    # 2. app_config 表：添加 knowledge_base_ids 列
    op.add_column(
        "app_config",
        sa.Column(
            "knowledge_base_ids",
            JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """回滚：将 knowledge_base_ids 改回 datasets，并删除 app_config 中的 knowledge_base_ids"""
    # 1. app_config 表：删除 knowledge_base_ids 列
    op.drop_column("app_config", "knowledge_base_ids")

    # 2. app_config_version 表：将 knowledge_base_ids 改回 datasets
    op.alter_column(
        "app_config_version",
        "knowledge_base_ids",
        new_column_name="datasets",
        existing_type=JSONB(astext_type=sa.Text()),
        existing_server_default=sa.text("'[]'::jsonb"),
        existing_nullable=False,
    )
