# api/internal/migration/versions/c6d7e8f9a0b1_remove_provider_credential_key.py
"""remove provider_credential_key from public_ai_feature_config

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-07-22 12:00:00.000000

provider_credential_key 是过度设计：模型池 model_pool_config 已包含 provider + base_url + API Key，
非 Chat 类功能（如文生图）直接从绑定的 model_config_id 对应记录读取凭证即可，无需独立凭证字段。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("public_ai_feature_config", "provider_credential_key")


def downgrade() -> None:
    op.add_column(
        "public_ai_feature_config",
        sa.Column("provider_credential_key", sa.String(length=128), nullable=True),
    )
