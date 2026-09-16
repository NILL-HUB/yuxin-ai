"""add admin agent conversation/message tables and builtin_key

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md
§10.1（独立会话表）与 §10.3（预置 Agent）。

为什么必须独立表：用户端 `conversation` / `message` 没有 admin 标识列，
admin 侧只能靠 `invoke_from ∈ {debugger, schedule}` 约定区分（设计 §11 盘点）。
独立表把归属列（`admin_user_id`）显式化，避免继续依赖约定。

`admin_agent.builtin_key` 用**部分唯一索引**兜底预置 Agent 的幂等：
同一管理员下同一 builtin_key 至多一条，自建 Agent 为 NULL 不受约束。

Revision ID: x1a2b3c4d5e7
Revises: w1e2f3a4b5c6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "x1a2b3c4d5e7"
down_revision = "w1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "admin_agent",
        sa.Column("builtin_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "admin_agent_owner_builtin_uniq",
        "admin_agent",
        ["owner_admin_user_id", "builtin_key"],
        unique=True,
        postgresql_where=sa.text("builtin_key IS NOT NULL"),
    )

    op.create_table(
        "admin_agent_conversation",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("admin_agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "title",
            sa.String(length=255),
            server_default=sa.text("''::character varying"),
            nullable=False,
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_agent_id"],
            ["admin_agent.id"],
            name="fk_admin_agent_conversation_admin_agent_id_admin_agent",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["admin_user.id"],
            name="fk_admin_agent_conversation_admin_user_id_admin_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_conversation_id"),
    )
    op.create_index(
        "admin_agent_conversation_admin_agent_id_idx",
        "admin_agent_conversation",
        ["admin_agent_id"],
    )
    op.create_index(
        "admin_agent_conversation_admin_user_id_idx",
        "admin_agent_conversation",
        ["admin_user_id"],
    )

    op.create_table(
        "admin_agent_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("uuid_generate_v4()"),
            nullable=False,
        ),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "role",
            sa.String(length=32),
            server_default=sa.text("'user'::character varying"),
            nullable=False,
        ),
        sa.Column(
            "content", sa.Text(), server_default=sa.text("''::text"), nullable=False
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["admin_agent_conversation.id"],
            name="fk_admin_agent_message_conversation_id_admin_agent_conversation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_admin_agent_message_id"),
    )
    op.create_index(
        "admin_agent_message_conversation_id_idx", "admin_agent_message", ["conversation_id"]
    )


def downgrade():
    op.drop_index("admin_agent_message_conversation_id_idx", table_name="admin_agent_message")
    op.drop_table("admin_agent_message")
    op.drop_index(
        "admin_agent_conversation_admin_user_id_idx", table_name="admin_agent_conversation"
    )
    op.drop_index(
        "admin_agent_conversation_admin_agent_id_idx", table_name="admin_agent_conversation"
    )
    op.drop_table("admin_agent_conversation")
    op.drop_index("admin_agent_owner_builtin_uniq", table_name="admin_agent")
    op.drop_column("admin_agent", "builtin_key")
