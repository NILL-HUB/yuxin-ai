"""drop run_os_task governance rows

Revision ID: 0a1b2c3d4e6f
Revises: i3d4e5f6a9b8
Create Date: 2026-09-08 00:00:00.000000

清理 Codex run_os_task 链路在 DB 中的残留行：
- tool_governance_policy：删除 builtin:codex_os:run_os_task 的高风险治理策略行
- builtin_tool：删除 codex_os provider 下 run_os_task 的镜像行（YAML 已移除，
  启动同步不会清理 catalog 中已删除的工具，需在此显式删除）

codex_os provider（builtin_tool_provider）保留：os_file_task / os_recycle_bin
仍由该 provider 承载。
"""
from alembic import op
import sqlalchemy as sa


revision = "0a1b2c3d4e6f"
down_revision = "i3d4e5f6a9b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM tool_governance_policy
            WHERE tool_id = 'builtin:codex_os:run_os_task'
               OR (provider_id = 'codex_os' AND tool_name = 'run_os_task')
            """
        )
    )
    op.execute(
        sa.text(
            """
            DELETE FROM builtin_tool
            WHERE name = 'run_os_task'
              AND provider_id = (
                  SELECT id FROM builtin_tool_provider WHERE name = 'codex_os'
              )
            """
        )
    )


def downgrade() -> None:
    pass
