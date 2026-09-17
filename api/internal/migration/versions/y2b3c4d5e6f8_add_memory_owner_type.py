"""add memory owner type columns for subject abstraction

设计依据：docs/superpowers/specs/2026-09-15-admin-agent-governance-design.md §8。

记忆主体此前硬编码为 Account（`owner_account_id` NOT NULL FK）。本迁移引入
`owner_type`(+`owner_admin_user_id`/`owner_agent_id`)，使记忆可归属管理员与 Agent。

**存量回填 `owner_type='user'`**：规格要求"存量全标 owner_type='user'，行为零变化"。
回填后 `owner_account_id` 原值不变、为非空，故既有读路径（按 owner_account_id 过滤）
逐字节不受影响。

向量分表 `user_memory_embedding_{dim}` 是**按维度动态建表**的（维度 1–2000），
无法在迁移里枚举全部表名，故此处对"已存在的分表"做一次 information_schema 扫描补列；
新建分表由 `EmbeddingTableRouter.ensure_tables_for_dimension()` 的 DDL 直接带上新列。

Revision ID: y2b3c4d5e6f8
Revises: x1a2b3c4d5e7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "y2b3c4d5e6f8"
down_revision = "x1a2b3c4d5e7"
branch_labels = None
depends_on = None

_USER_MEMORY_EMBEDDING_PREFIX = "user_memory_embedding_"


def upgrade():
    # 1) 主表补三列（owner_type 先可空，回填后再收紧为 NOT NULL，避免锁表时报"已有非空行")
    op.add_column(
        "user_memory",
        sa.Column("owner_type", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "user_memory",
        sa.Column(
            "owner_admin_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "user_memory",
        sa.Column("owner_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 2) 存量回填：全部标 user（原 owner_account_id 不变 → 行为零变化）
    op.execute("UPDATE user_memory SET owner_type = 'user' WHERE owner_type IS NULL")

    # 3) 回填后再收紧非空 + 默认值
    op.alter_column(
        "user_memory",
        "owner_type",
        nullable=False,
        server_default=sa.text("'user'::character varying"),
    )

    # 4) 外键（与模型声明一致；FK 名遵循本仓 fk_<table>_<col>_<target> 约定）
    op.create_foreign_key(
        "fk_user_memory_owner_admin_user_id_admin_user",
        "user_memory",
        "admin_user",
        ["owner_admin_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_user_memory_owner_agent_id_admin_agent",
        "user_memory",
        "admin_agent",
        ["owner_agent_id"],
        ["id"],
    )

    # 5) 索引
    op.create_index("user_memory_owner_admin_idx", "user_memory", ["owner_admin_user_id"])
    op.create_index("user_memory_owner_agent_idx", "user_memory", ["owner_agent_id"])

    # 6) 已存在的向量分表补列（动态表名，故用扫描而非枚举）
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    for (table_name,) in rows:
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_type VARCHAR(16) NOT NULL DEFAULT 'user'"
        )
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_admin_user_id UUID REFERENCES admin_user(id)"
        )
        op.execute(
            f"ALTER TABLE {table_name} "
            "ADD COLUMN IF NOT EXISTS owner_agent_id UUID REFERENCES admin_agent(id)"
        )
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {table_name}_owner_agent_idx "
            f"ON {table_name} (owner_agent_id)"
        )


def downgrade():
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name LIKE :prefix"
        ),
        {"prefix": f"{_USER_MEMORY_EMBEDDING_PREFIX}%"},
    ).fetchall()
    for (table_name,) in rows:
        op.execute(f"DROP INDEX IF EXISTS {table_name}_owner_agent_idx")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_agent_id")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_admin_user_id")
        op.execute(f"ALTER TABLE {table_name} DROP COLUMN IF EXISTS owner_type")

    op.drop_index("user_memory_owner_agent_idx", table_name="user_memory")
    op.drop_index("user_memory_owner_admin_idx", table_name="user_memory")
    op.drop_constraint(
        "fk_user_memory_owner_agent_id_admin_agent", "user_memory", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_user_memory_owner_admin_user_id_admin_user", "user_memory", type_="foreignkey"
    )
    op.drop_column("user_memory", "owner_agent_id")
    op.drop_column("user_memory", "owner_admin_user_id")
    op.drop_column("user_memory", "owner_type")
