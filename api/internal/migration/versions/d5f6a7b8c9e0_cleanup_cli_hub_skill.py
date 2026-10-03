"""cleanup cli-hub skill_package rows

cli-hub 技能（纯提示词、无执行器，且与"仅管理员手动注册"的安全模型冲突）已删除；
技能目录同步只增不删，DB 中会残留 `skill_package` / `skill_package_version` 记录，
故需显式清理。

Revision ID: d5f6a7b8c9e0
Revises: c4e5f6a7b8d9
"""

from alembic import op
import sqlalchemy as sa

revision = "d5f6a7b8c9e0"
down_revision = "c4e5f6a7b8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM skill_package_version WHERE skill_package_id IN "
            "(SELECT id FROM skill_package WHERE source_key = 'cli-hub')"
        )
    )
    op.execute(sa.text("DELETE FROM skill_package WHERE source_key = 'cli-hub'"))


def downgrade() -> None:
    # 数据删除不可逆；catalog 文件已删除，重新同步也不会恢复该技能包。
    pass
