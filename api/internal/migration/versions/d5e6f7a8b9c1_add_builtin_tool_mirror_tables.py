# api/internal/migration/versions/d5e6f7a8b9c1_add_builtin_tool_mirror_tables.py
"""add builtin tool mirror tables (builtin_tool_provider + builtin_tool)

Revision ID: d5e6f7a8b9c1
Revises: c4d5e6f7a8b0
Create Date: 2026-07-27 17:00:00.000000

为 builtin 工具元数据建立 DB 镜像表，支持 admin 后台编辑。

设计动机：
- builtin 工具有 51 个，由 YAML 元数据 + Python 执行代码组成
- Python 执行代码无法迁移到数据库，必须保留本地
- YAML 元数据（name/label/description/task_keywords/icon/category）可以迁移到 DB
- 启动时由 BuiltinToolSyncService 从 YAML 同步到 DB（source="catalog"）
- admin 后台编辑只改 DB（source="custom"），不会回写 YAML
- DB 不可用时 BuiltinProviderManager 回退到 YAML 加载（保证可用性）

注意：本 migration 只建表，不同步 YAML 数据。同步逻辑由
BuiltinToolSyncService.sync_yaml_to_db() 在启动时执行。

revision ID 说明：任务规约要求 revision=d5e6f7a8b9c0，但该 ID 已被
d5e6f7a8b9c0_add_credit_transaction_idempotent_index.py 占用，为避免
revision 冲突导致 alembic 历史损坏，改用 d5e6f7a8b9c1。
down_revision 仍按规约保持 c4d5e6f7a8b0。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c1"
down_revision = "c4d5e6f7a8b0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. builtin_tool_provider 表
    op.create_table(
        "builtin_tool_provider",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column("icon", sa.String(length=512), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("background", sa.String(length=64), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("category", sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'catalog'::character varying")),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_builtin_tool_provider_id"),
        sa.UniqueConstraint("name", name="uq_builtin_tool_provider_name"),
    )
    op.create_index(
        "builtin_tool_provider_name_idx",
        "builtin_tool_provider",
        ["name"],
    )

    # 2. builtin_tool 表
    op.create_table(
        "builtin_tool",
        sa.Column("id", sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column("params", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("task_keywords", JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("python_module", sa.String(length=1024), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column("source", sa.String(length=32), nullable=False, server_default=sa.text("'catalog'::character varying")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint("id", name="pk_builtin_tool_id"),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["builtin_tool_provider.id"],
            name="fk_builtin_tool_provider_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "builtin_tool_provider_id_idx",
        "builtin_tool",
        ["provider_id"],
    )
    op.create_index(
        "builtin_tool_name_idx",
        "builtin_tool",
        ["name"],
    )
    op.create_index(
        "builtin_tool_task_keywords_idx",
        "builtin_tool",
        ["task_keywords"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("builtin_tool_task_keywords_idx", table_name="builtin_tool")
    op.drop_index("builtin_tool_name_idx", table_name="builtin_tool")
    op.drop_index("builtin_tool_provider_id_idx", table_name="builtin_tool")
    op.drop_table("builtin_tool")

    op.drop_index("builtin_tool_provider_name_idx", table_name="builtin_tool_provider")
    op.drop_table("builtin_tool_provider")
