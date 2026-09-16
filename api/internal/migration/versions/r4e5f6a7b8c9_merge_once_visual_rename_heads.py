"""merge schedule-once, visual-embedding and host-os-rename heads

Revision ID: r4e5f6a7b8c9
Revises: dae1f2a3b4c5, o9d0e1f2a3b4, q3d4e5f6a7b8
Create Date: 2026-09-15 00:00:00.000000

本地工作区同时存在三条互不相交的迁移链，合并为一个 head，保证
`alembic upgrade head` 可正常执行：

1. `o9d0e1f2a3b4`（schedule_task.run_at，单次任务）—— 自 `p1a2b3c4d5e6`
   把 down_revision 从它改为 `n8c9d0e1f2a3` 后，长期悬为独立分支 head。
2. `dae1f2a3b4c5`（视觉向量：`c9d0e1f2a3b4` 建表 + seed 硅基流动 VL 模型）。
3. `q3d4e5f6a7b8`（builtin provider `codex_os` → `host_os`）。

背景：`p1a2b3c4d5e6_add_knowledge_product_form_base.py` 的 docstring 已预告
"若后续 `o9d0e1f2a3b4` 被提交，会与本迁移形成两个 head，必须补一个 merge 迁移"，
本迁移即为兑现该约束。守卫测试
`test/internal/migration/test_migration_graph_integrity.py` 按 **git 跟踪文件**
判定单 head，三条分支被提交后即会失败。

重放安全性：合并后 `upgrade head` 会重放此前未记录进 `alembic_version` 的分支，
各迁移均为幂等实现——`o9d0e1f2a3b4` 用 `ADD COLUMN IF NOT EXISTS`，
`dae1f2a3b4c5` 用 `NOT EXISTS` 保护，`q2b3c4d5e6f7` 为 UPDATE。
"""
from alembic import op


revision = "r4e5f6a7b8c9"
down_revision = ("dae1f2a3b4c5", "o9d0e1f2a3b4", "q3d4e5f6a7b8")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
