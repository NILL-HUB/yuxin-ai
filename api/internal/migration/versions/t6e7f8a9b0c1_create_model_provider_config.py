# api/internal/migration/versions/t6e7f8a9b0c1_create_model_provider_config.py
"""create model_provider_config table

Revision ID: t6e7f8a9b0c1
Revises: s3d4e5f6a7b8
Create Date: 2026-07-16 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "t6e7f8a9b0c1"
down_revision = "s3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_provider_config",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(length=512), nullable=True),
        sa.Column("background", sa.String(length=32), nullable=False, server_default=sa.text("'#FFFFFF'::character varying")),
        sa.Column("default_base_url", sa.String(length=512), nullable=False),
        sa.Column("supported_model_types", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[\"chat\"]'::jsonb")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'active'::character varying")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_model_provider_config_id"),
    )
    op.create_index("ix_model_provider_config_name", "model_provider_config", ["name"], unique=True)
    op.create_index("ix_model_provider_config_status", "model_provider_config", ["status"])


def downgrade() -> None:
    op.drop_index("ix_model_provider_config_status", table_name="model_provider_config")
    op.drop_index("ix_model_provider_config_name", table_name="model_provider_config")
    op.drop_table("model_provider_config")
