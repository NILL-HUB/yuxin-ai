"""add credentials to builtin_tool_provider

Revision ID: m7c8d9e0f1a2
Revises: l6b7c8d9e0f1
Create Date: 2026-09-29 00:00:00.000000

第三方工具密钥（搜索类等）此前只走 env、后台无处可配。本迁移给
builtin_tool_provider 增加 credentials（加密 JSONB，键=env 名），
使 admin 可配可看；运行时经 ToolCredentialResolver「DB 优先 → env 兜底」读取，
升级瞬间（DB 为空）行为与现状逐字节一致。

设计取舍：不另加 credential_keys 列——"某 provider 需要哪些键"由代码
（`BuiltinToolCredentialService.PROVIDER_CREDENTIAL_KEYS`）声明，属开发者定义而非管理员配置，
避免冗余存储与漂移。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "m7c8d9e0f1a2"
down_revision = "l6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "builtin_tool_provider",
        sa.Column("credentials", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    op.drop_column("builtin_tool_provider", "credentials")
