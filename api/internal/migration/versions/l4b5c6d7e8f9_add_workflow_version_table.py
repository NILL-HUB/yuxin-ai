"""add workflow_version table

Revision ID: l4b5c6d7e8f9
Revises: k3a4b5c6d7e8
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "l4b5c6d7e8f9"
down_revision = "k3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workflow_version",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("graph", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_current_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("summary", sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)"), server_onupdate=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_version_id"),
    )
    op.create_index("workflow_version_workflow_id_idx", "workflow_version", ["workflow_id"])
    op.create_index("workflow_version_is_current_idx", "workflow_version", ["is_current_published"])
    op.create_foreign_key(
        "fk_workflow_version_workflow_id_workflow",
        "workflow_version",
        "workflow",
        ["workflow_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade():
    op.drop_constraint("fk_workflow_version_workflow_id_workflow", "workflow_version", type_="foreignkey")
    op.drop_index("workflow_version_is_current_idx", table_name="workflow_version")
    op.drop_index("workflow_version_workflow_id_idx", table_name="workflow_version")
    op.drop_table("workflow_version")
