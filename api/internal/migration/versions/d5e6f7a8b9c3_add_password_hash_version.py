"""add password hash version columns

Revision ID: d5e6f7a8b9c3
Revises: f6a7b8c9d0e1
Create Date: 2026-08-15 00:00:00.000000

为 account / admin_user 表添加 password_version 列，标识密码哈希的迭代参数：
- 1 = PBKDF2-HMAC-SHA256 10,000 次迭代（历史存量哈希）
- 2 = PBKDF2-HMAC-SHA256 600,000 次迭代（当前推荐参数，OWASP 2023）

存量数据默认 version=1，用户/管理员下次成功登录时透明升级为 version=2。
"""
from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c3"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "account",
        sa.Column("password_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "admin_user",
        sa.Column("password_version", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("admin_user", "password_version")
    op.drop_column("account", "password_version")
