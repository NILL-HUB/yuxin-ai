"""purge orphan rows of test-era accounts (sessions/credits/devices/tags)

与 `e2f3a4b5c6d7`（file_center_entry 孤儿）同源：测试环境存在绕过回收站直接删除
`account` 行的历史操作，留下无主数据。本迁移清理其余各表，判定口径统一为
「归属列 IS NOT NULL 且所属 account 行不存在」；`IS NULL` 表示系统级数据或按设计
解绑（如审计日志、公共知识库），一律不动。

账号正常删除路径（purge_account）的清理清单已覆盖下列全部表——本迁移只清历史遗留，
不改业务代码。

级联顺序：
1. tag 关联表（app_tag / knowledge_base_tag / knowledge_document_tag / workflow_tag）先清
2. conversation.desktop_device_id 先置 NULL 解绑（列为 varchar，需 ::text）
3. credit_transaction（流水）先于 credit_account（账户）

幂等：可重复执行；downgrade 不恢复（账号行删除是终态）。

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
"""

from alembic import op
import sqlalchemy as sa

revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


_ORPHAN_TAG_SUBQUERY = (
    "SELECT t.id FROM tag t WHERE t.account_id IS NOT NULL "
    "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = t.account_id)"
)


def upgrade() -> None:
    # 1) 标签：先清各关联表，再删标签本体
    for assoc in ("app_tag", "knowledge_base_tag", "knowledge_document_tag", "workflow_tag"):
        op.execute(
            sa.text(f"DELETE FROM {assoc} WHERE tag_id IN ({_ORPHAN_TAG_SUBQUERY})")
        )
    op.execute(
        sa.text(
            "DELETE FROM tag WHERE account_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = tag.account_id)"
        )
    )

    # 2) 设备：先解绑会话引用（varchar 列），再删设备
    op.execute(
        sa.text(
            "UPDATE conversation SET desktop_device_id = NULL WHERE desktop_device_id IN ("
            "  SELECT x.id::text FROM desktop_device x WHERE x.account_id IS NOT NULL"
            "  AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = x.account_id)"
            ")"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM desktop_device WHERE account_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = desktop_device.account_id)"
        )
    )

    # 3) 积分：流水先于账户
    op.execute(
        sa.text(
            "DELETE FROM credit_transaction WHERE account_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = credit_transaction.account_id)"
        )
    )
    op.execute(
        sa.text(
            "DELETE FROM credit_account WHERE account_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = credit_account.account_id)"
        )
    )

    # 4) 会话
    op.execute(
        sa.text(
            "DELETE FROM account_session WHERE account_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM account a WHERE a.id = account_session.account_id)"
        )
    )


def downgrade() -> None:
    # 数据删除不可逆；孤儿行无恢复语义（其账号已不存在）。
    pass
