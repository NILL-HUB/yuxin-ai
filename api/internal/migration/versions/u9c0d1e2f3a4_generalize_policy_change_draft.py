"""generalize policy_change_draft into a generic admin change draft

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §5.2。

`suggestion_id` 由 NOT NULL 改为可空（通用草稿可不来自路由建议），
并补一条 (status, created_at) 索引支撑「列出全部待应用草稿」。
路由既有行为与三个 policy_type 取值保持兼容，存量数据零迁移。

Revision ID: u9c0d1e2f3a4
Revises: t8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa

revision = "u9c0d1e2f3a4"
down_revision = "t8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "policy_change_draft",
        "suggestion_id",
        existing_type=sa.UUID(),
        nullable=True,
    )
    op.create_index(
        "policy_change_draft_status_created_idx",
        "policy_change_draft",
        ["status", "created_at"],
    )


def downgrade():
    # 回退前先清掉无法回填的通用草稿（suggestion_id IS NULL 的行在
    # NOT NULL 约束下无法存在），否则 alter 会直接失败。
    op.execute("DELETE FROM policy_change_draft WHERE suggestion_id IS NULL")
    op.drop_index(
        "policy_change_draft_status_created_idx",
        table_name="policy_change_draft",
    )
    op.alter_column(
        "policy_change_draft",
        "suggestion_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
