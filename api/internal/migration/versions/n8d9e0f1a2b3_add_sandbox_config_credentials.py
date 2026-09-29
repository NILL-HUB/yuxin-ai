"""add credentials to sandbox_config

Revision ID: n8d9e0f1a2b3
Revises: m7c8d9e0f1a2
Create Date: 2026-09-29 00:00:00.000000

沙箱后端凭证（如 E2B_API_KEY / E2B_DOMAIN）此前只走 env、后台无处可配。
本迁移给 sandbox_config 增加 credentials（加密 JSONB，键=env 名），使 admin 可配可看：
运行时经 `SandboxConfigService.resolve_credentials`「DB 解密优先 → env 兜底」读取，
升级瞬间（DB 为空）行为与现状逐字节一致。

与工具凭证（`builtin_tool_provider.credentials`）同口径，复用 `tool_credential_encryptor`。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "n8d9e0f1a2b3"
down_revision = "m7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "sandbox_config",
        sa.Column("credentials", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    op.drop_column("sandbox_config", "credentials")
