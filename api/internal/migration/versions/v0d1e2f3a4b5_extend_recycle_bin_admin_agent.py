"""extend recycle_bin to support admin_agent deletion source

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §7.1。

背景：既有 deleted_by_type='agent' 被硬约束为仅 7 类用户可见资源
（USER_VISIBLE_RESOURCE_TYPES），admin 专属资源（app/workflow/skill/mcp/
api_tool/system_prompt/upload_file）以该来源入站会抛 ValidateErrorException。
新增 'admin_agent' 来源表达"管理端 Agent 代删"，与 'agent'（用户侧）区分。

本迁移只做两件与 DB 相关的事：
1. 为 deleted_by_type 建索引（跨来源查询变多）；
2. 兜底修正历史误标——把「admin 专属资源 + agent 来源」的行归位为 admin_agent
   （这类行在当前代码下本就无法产生，属防御性清理，预期影响 0 行）。
无列变更（deleted_by_type 已是 VARCHAR(16)，长度足够）。

Revision ID: v0d1e2f3a4b5
Revises: u9c0d1e2f3a4
"""
from alembic import op
import sqlalchemy as sa  # noqa: F401  （迁移风格一致性）

revision = "v0d1e2f3a4b5"
down_revision = "u9c0d1e2f3a4"
branch_labels = None
depends_on = None

# 与 RecycleBinService.USER_VISIBLE_RESOURCE_TYPES 同源。此处硬编码是刻意的：
# 迁移必须固化"当时的事实"，不能随代码常量漂移（否则历史迁移在新代码下会改变含义）。
_USER_VISIBLE = (
    "knowledge_base",
    "knowledge_document",
    "os_file",
    "schedule_task",
    "external_data_source",
    "conversation",
    "memory",
)


def upgrade():
    op.create_index(
        "recycle_bin_deleted_by_type_idx2", "recycle_bin", ["deleted_by_type"]
    )
    visible = ", ".join(f"'{t}'" for t in _USER_VISIBLE)
    op.execute(
        "UPDATE recycle_bin "
        "SET deleted_by_type = 'admin_agent' "
        f"WHERE deleted_by_type = 'agent' AND resource_type NOT IN ({visible})"
    )


def downgrade():
    # 归位回 agent 会让这些行重新落回"用户侧来源 + admin 专属资源"的非法组合，
    # 因此降级时一并改回 admin（保守且不产生非法状态）。
    op.execute(
        "UPDATE recycle_bin SET deleted_by_type = 'admin' "
        "WHERE deleted_by_type = 'admin_agent'"
    )
    op.drop_index("recycle_bin_deleted_by_type_idx2", table_name="recycle_bin")
