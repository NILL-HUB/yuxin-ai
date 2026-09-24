"""add model_key_config.circuit_opened_at

Revision ID: i3d4e5f6a7b0
Revises: g1b2c3d4e5f8
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "i3d4e5f6a7b0"
down_revision = "g1b2c3d4e5f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_key_config",
        sa.Column("circuit_opened_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_key_config", "circuit_opened_at")
