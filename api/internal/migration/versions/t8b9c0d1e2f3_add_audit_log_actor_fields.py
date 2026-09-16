"""add audit_log.actor_type / agent_id

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §9。
用于区分"管理员本人操作"与"管理员让 Agent 代操作"。

存量行由 server_default='human' 自动填充（语义正确：历史记录都是人工操作），
因此**无需数据回填语句**，升级是行为零变化的。

Revision ID: t8b9c0d1e2f3
Revises: s5f6a7b8c9d0
"""
from alembic import op
import sqlalchemy as sa

revision = "t8b9c0d1e2f3"
down_revision = "s5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "audit_log",
        sa.Column(
            "actor_type",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'human'::character varying"),
        ),
    )
    op.add_column("audit_log", sa.Column("agent_id", sa.UUID(), nullable=True))
    op.create_index("audit_log_actor_type_idx", "audit_log", ["actor_type"])
    op.create_index("audit_log_agent_id_idx", "audit_log", ["agent_id"])


def downgrade():
    op.drop_index("audit_log_agent_id_idx", table_name="audit_log")
    op.drop_index("audit_log_actor_type_idx", table_name="audit_log")
    op.drop_column("audit_log", "agent_id")
    op.drop_column("audit_log", "actor_type")
