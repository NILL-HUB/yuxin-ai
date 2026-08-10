"""decouple admin resource ownership

Revision ID: e0a1b2c3d4e5
Revises: d2e3f4a5b6c0
Create Date: 2026-08-05 00:00:00.000000

完全解耦管理员与用户端账号后，管理员创建的资源不再归属到某个用户账号，
而是作为平台级资源存在。为此：
- app / workflow / api_tool_provider / api_tool / upload_file 的 account_id 改为可空
- app / workflow / api_tool_provider 新增 created_by_admin 记录创建管理员，用于展示归属者
"""
from alembic import op
import sqlalchemy as sa


revision = "e0a1b2c3d4e5"
down_revision = "d2e3f4a5b6c0"
branch_labels = None
depends_on = None


def _make_account_id_nullable(table: str) -> None:
    op.alter_column(table, "account_id", existing_type=sa.UUID(), nullable=True)


def upgrade():
    # 1) account_id 改为可空（平台级资源无需归属账号）
    for table in ("app", "workflow", "api_tool_provider", "api_tool", "upload_file"):
        _make_account_id_nullable(table)

    # 2) 新增 created_by_admin 字段（记录创建管理员，用于展示归属者）
    for table in ("app", "workflow", "api_tool_provider"):
        op.add_column(table, sa.Column("created_by_admin", sa.UUID(), nullable=True))
        op.create_index(
            f"ix_{table}_created_by_admin",
            table,
            ["created_by_admin"],
        )
        op.create_foreign_key(
            f"fk_{table}_created_by_admin_admin_user",
            table,
            "admin_user",
            ["created_by_admin"],
            ["id"],
        )


def downgrade():
    for table in ("app", "workflow", "api_tool_provider"):
        op.drop_constraint(f"fk_{table}_created_by_admin_admin_user", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_created_by_admin", table_name=table)
        op.drop_column(table, "created_by_admin")

    for table in ("upload_file", "api_tool", "api_tool_provider", "workflow", "app"):
        op.alter_column(table, "account_id", existing_type=sa.UUID(), nullable=False)
