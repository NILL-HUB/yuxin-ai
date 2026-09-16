"""add once-trigger fields to schedule_task

Revision ID: o9d0e1f2a3b4
Revises: n8c9d0e1f2a3
Create Date: 2026-09-13 00:00:00.000000

单次任务（trigger_type=once）支持：
1. 新增 run_at 列：单次任务的执行时刻（UTC naive，与 next_run_at 比较语义一致）。
2. backfill：历史行 trigger_type 为 cron/interval 时 run_at 保持 NULL，语义不变。

**必须幂等**（为什么用 ADD COLUMN IF NOT EXISTS 而不是 op.add_column）：
本 revision 的 down_revision 指向 `n8c9d0e1f2a3`，而 `p1a2b3c4d5e6` 曾把
down_revision 从 `o9d0e1f2a3b4` 改为 `n8c9d0e1f2a3`（见该文件 docstring），
导致本 revision 长期是**独立分支 head**、未进入主链。期间开发库上
`schedule_task.run_at` 列可能已被旁路创建，但 `alembic_version` 未记录本
revision。合并 head 后 `alembic upgrade head` 会重放本迁移，
`op.add_column` 将直接抛 `column "run_at" of relation "schedule_task"
already exists`，使整条升级链失败。改为 `IF NOT EXISTS` 后无论列是否存在
都能安全通过，与 `c9d0e1f2a3b4`（建表）/ `dae1f2a3b4c5`（seed）的幂等风格一致。
"""
from alembic import op


revision = "o9d0e1f2a3b4"
down_revision = "n8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE schedule_task "
        "ADD COLUMN IF NOT EXISTS run_at TIMESTAMP WITHOUT TIME ZONE"
    )


def downgrade():
    op.execute("ALTER TABLE schedule_task DROP COLUMN IF EXISTS run_at")
