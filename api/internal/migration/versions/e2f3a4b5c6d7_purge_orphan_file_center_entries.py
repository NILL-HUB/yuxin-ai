"""purge orphan file_center_entry rows (account gone)

清理「所属账号已不存在」的 `file_center_entry` 残留行（孤儿数据）。

背景：账号删除走「进回收站 + 留存期到期 `purge_account` 全量清空」，
`purge_account` 的清理清单已覆盖本表；但测试环境存在绕过回收站直接删除
`account` 行的历史操作，留下了无主节点（本机实测 2 条）。本迁移按
「account 行不存在」判定并删除，幂等、对生产同样安全（账号行删除是终态）。

Revision ID: e2f3a4b5c6d7
Revises: f9a0b1c2d3e4
"""

from alembic import op
import sqlalchemy as sa

revision = "e2f3a4b5c6d7"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM file_center_entry e "
            "WHERE NOT EXISTS (SELECT 1 FROM account a WHERE a.id = e.account_id)"
        )
    )


def downgrade() -> None:
    # 数据删除不可逆；孤儿节点无恢复语义（其账号已不存在）。
    pass
