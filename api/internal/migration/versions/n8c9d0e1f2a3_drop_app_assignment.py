"""drop app_assignment table and purge its orphan audit logs

Revision ID: n8c9d0e1f2a3
Revises: m7b8c9d0e1f2
Create Date: 2026-09-13 00:00:00.000000

「管理员分配应用」功能已下线：
1. 删除 audit_log 中 resource_type='app_assignment' 的孤儿记录
   （对应 i18n 标签已随功能一并移除，保留会导致审计页出现“无键值记录”）。
2. drop table app_assignment（含索引与 FK）。

downgrade 不可逆（表与审计记录均已删除），需走备份恢复。
"""
from alembic import op
from sqlalchemy import text

revision = "n8c9d0e1f2a3"
down_revision = "m7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    removed_audits = conn.execute(
        text("DELETE FROM audit_log WHERE resource_type = 'app_assignment'")
    ).rowcount

    op.drop_table("app_assignment")

    print(f"[migration] 清理 app_assignment 孤儿审计：{removed_audits} 行；已 drop table app_assignment")


def downgrade():
    raise NotImplementedError(
        "该迁移不可逆（app_assignment 表与相关审计记录均已删除），请走备份恢复。"
    )
