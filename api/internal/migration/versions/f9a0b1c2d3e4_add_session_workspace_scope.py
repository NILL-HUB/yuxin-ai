"""add session_workspace_scope

会话工作区授权表：把「用户批准的会话级额外工作目录」落库，worker 侧按
`安全根 ∪ 会话授权根` 校验，授权范围内享受与安全根一致的治理能力
（写前快照、回收站、删除守卫）。

设计（已落地）：docs/archive/superpowers-specs/2026-10-04-session-workspace-scope-design.md

Revision ID: f9a0b1c2d3e4
Revises: a9b8c7d6e5f4
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f9a0b1c2d3e4"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_workspace_scope",
        sa.Column(
            "id",
            postgresql.UUID(),
            nullable=False,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("account_id", postgresql.UUID(), nullable=False),
        sa.Column("session_id", sa.String(length=255), nullable=False),
        sa.Column("scope_root", sa.String(length=1024), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'granted'::character varying"),
        ),
        sa.Column(
            "granted_via",
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(0)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_session_workspace_scope_id"),
    )
    op.create_index(
        "session_workspace_scope_account_idx",
        "session_workspace_scope",
        ["account_id"],
    )
    op.create_index(
        "session_workspace_scope_session_idx",
        "session_workspace_scope",
        ["session_id"],
    )
    op.create_index(
        "session_workspace_scope_unique_idx",
        "session_workspace_scope",
        ["account_id", "session_id", "scope_root"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("session_workspace_scope_unique_idx", table_name="session_workspace_scope")
    op.drop_index("session_workspace_scope_session_idx", table_name="session_workspace_scope")
    op.drop_index("session_workspace_scope_account_idx", table_name="session_workspace_scope")
    op.drop_table("session_workspace_scope")
