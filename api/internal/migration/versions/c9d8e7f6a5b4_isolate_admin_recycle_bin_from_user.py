"""isolate admin recycle bin entries from user recycle bin

Revision ID: c9d8e7f6a5b4
Revises: e4f5a6b7c8d9
Create Date: 2026-08-17 00:00:00.000000

历史数据中 app/workflow/skill/mcp/api_tool/system_prompt/upload_file 等
admin 专属资源可能被误标为 deleted_by_type=user/agent，导致它们出现在用户回收站。
本迁移把这些条目归位到 admin 回收站（deleted_by_type=admin），不删除任何数据。
"""
from alembic import op
import sqlalchemy as sa


revision = "c9d8e7f6a5b4"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE recycle_bin "
            "SET deleted_by_type = 'admin', "
            "remark = CASE "
            "  WHEN remark = '' THEN :remark "
            "  ELSE remark || '；' || :remark "
            "END "
            "WHERE deleted_by_type IN ('user', 'agent') "
            "AND resource_type NOT IN ("
            "  'knowledge_base',"
            "  'knowledge_document',"
            "  'os_file',"
            "  'schedule_task',"
            "  'external_data_source',"
            "  'conversation',"
            "  'memory'"
            ")"
        ),
        {"remark": "历史误标 user/agent，已隔离至管理员回收站"},
    )


def downgrade():
    # 原始 deleted_by_type 无法可靠还原，降级时仅清理迁移标记。
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE recycle_bin "
            "SET remark = REPLACE(remark, '；历史误标 user/agent，已隔离至管理员回收站', '') "
            "WHERE remark LIKE '%历史误标 user/agent，已隔离至管理员回收站%'"
        )
    )
