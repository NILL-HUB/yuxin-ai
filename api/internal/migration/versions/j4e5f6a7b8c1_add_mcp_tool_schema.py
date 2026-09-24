"""add mcp_provider.tool_schema

Revision ID: j4e5f6a7b8c1
Revises: i3d4e5f6a7b0
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "j4e5f6a7b8c1"
down_revision = "i3d4e5f6a7b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_provider",
        sa.Column(
            "tool_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("mcp_provider", "tool_schema")
