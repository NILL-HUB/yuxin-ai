"""merge session scope / device binding / cli-hub heads

收敛迁移图的三条分支：
- `d5f6a7b8c9e0`（cli-hub 技能清理链尾）
- `g2b3c4d5e6f7`（model pool 描述字段链尾）
- `b7c8d9e0f1a2`（会话设备绑定，手机端 P0）

三者互不相干且都已是各自链尾，合并为单 head 后由
`b1c2d3e4f5a6_add_session_workspace_scope` 继续。

Revision ID: a9b8c7d6e5f4
Revises: g2b3c4d5e6f7, d5f6a7b8c9e0, b7c8d9e0f1a2
"""

from alembic import op  # noqa: F401  （merge 迁移无结构变更，保留 import 供后续追加）
import sqlalchemy as sa  # noqa: F401

revision = "a9b8c7d6e5f4"
down_revision = ("g2b3c4d5e6f7", "d5f6a7b8c9e0", "b7c8d9e0f1a2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
