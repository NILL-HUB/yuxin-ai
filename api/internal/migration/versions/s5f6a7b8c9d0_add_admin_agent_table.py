"""add admin_agent table

Revision ID: s5f6a7b8c9d0
Revises: t7a8b9c0d1e2
Create Date: 2026-09-16 00:00:00.000000

新增 admin_agent 表：承载管理端 Agent 定义、权限子集与自动化级别（设计 §10.1）。

down_revision 指向**唯一 head** `t7a8b9c0d1e2`。注意本表有外键指向
`admin_user`（建表迁移 `a2b3c4d5e6f7`，位于更早的祖先链上），满足
test_migration_empty_db_smoke.py 的「被引用表的 create_table 必须在祖先链」约束。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "s5f6a7b8c9d0"
down_revision = "t7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_agent",
        sa.Column("id", sa.UUID(), nullable=False,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("owner_admin_user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False,
                  server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=False,
                  server_default=sa.text("''::text")),
        sa.Column("prompt_key", sa.String(length=128), nullable=True),
        sa.Column("granted_permissions", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("automation_policy", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("budget_config", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(
            ["owner_admin_user_id"], ["admin_user.id"],
            name="fk_admin_agent_owner_admin_user_id_admin_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_id"),
    )
    op.create_index("admin_agent_owner_admin_user_id_idx", "admin_agent",
                    ["owner_admin_user_id"])
    op.create_index("admin_agent_enabled_idx", "admin_agent", ["enabled"])


def downgrade():
    op.drop_index("admin_agent_enabled_idx", table_name="admin_agent")
    op.drop_index("admin_agent_owner_admin_user_id_idx", table_name="admin_agent")
    op.drop_table("admin_agent")
