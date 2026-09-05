"""add password_changed_at

Revision ID: a9f0b1c2d3e8
Revises: a0b1c2d3e4f5
Create Date: 2026-08-23 00:00:00.000000

为 account / admin_user 增加 password_changed_at 字段：
密码修改后立即吊销旧登录会话，旧 token 不再有效。
"""
from alembic import op
import sqlalchemy as sa


revision = "a9f0b1c2d3e8"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return rows.scalar() is not None


def upgrade():
    if not _has_column("account", "password_changed_at"):
        op.add_column("account", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    if not _has_column("admin_user", "password_changed_at"):
        op.add_column("admin_user", sa.Column("password_changed_at", sa.DateTime(), nullable=True))


def downgrade():
    if _has_column("admin_user", "password_changed_at"):
        op.drop_column("admin_user", "password_changed_at")
    if _has_column("account", "password_changed_at"):
        op.drop_column("account", "password_changed_at")
