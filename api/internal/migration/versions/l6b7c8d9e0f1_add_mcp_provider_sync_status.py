"""add mcp_provider sync status columns

Revision ID: l6b7c8d9e0f1
Revises: k5a6b7c8d9e0
Create Date: 2026-09-29 00:00:00.000000

MCP 工具同步此前失败被静默吞掉（工具工厂异常返回 []、调用方丢弃返回值），
管理员误以为 MCP 配置成功（体检 P0-5）。本迁移给 mcp_provider 增加同步状态列，
使失败可见、可排查（对齐 skill_package.sync_status 的既有范式）。

取值语义（服务层写入，`McpService.sync_mcp_tools`）：
  ready           成功同步且至少 1 个工具
  empty           连接成功但服务端无工具
  failed          连接/协议/鉴权失败（原因见 sync_error）
  not_configured  前置缺失（transport 不受支持 / stdio 命令不可执行），未真正发起
  ''              从未尝试同步（迁移后既有行）
"""
from alembic import op
import sqlalchemy as sa


revision = "l6b7c8d9e0f1"
down_revision = "k5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mcp_provider",
        sa.Column("sync_status", sa.String(64), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "mcp_provider",
        sa.Column("sync_error", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "mcp_provider",
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("mcp_provider", "last_synced_at")
    op.drop_column("mcp_provider", "sync_error")
    op.drop_column("mcp_provider", "sync_status")
