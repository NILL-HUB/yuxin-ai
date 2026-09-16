# api/internal/migration/versions/a3d4e5f6g7b8_create_embedding_dim_tables_and_migrate.py
"""create embedding dimension tables and migrate existing vectors

创建按维度分表的向量存储表（1536 维），并将 user_memory.embedding 和
knowledge_segment.embedding 中的现有向量迁移到新表。

按维度分表架构：
    - user_memory_embedding_{dim}: 存储 user_memory 的向量（按维度分表）
    - knowledge_segment_embedding_{dim}: 存储 knowledge_segment 的向量（按维度分表）
    - 原表的 embedding 列保留但不再使用（后续迁移中废弃）

**修复记录（2026-09，空库验证）**：`user_memory.embedding` 与
`knowledge_segment.embedding` 这两列在**建表迁移中并没有创建**
（`d1e2f3a4b5c7` 建 `user_memory` / `knowledge_segment` 时均无 embedding 列），
但 ORM 模型声明了它们，且本迁移第 3/4 步要 SELECT 它们做数据搬运。原实现直接
`SELECT ... embedding`，空库上抛：

    column "embedding" does not exist
    (There is a column named "embedding" in table "user_memory_embedding_1536",
     but it cannot be referenced from this part of the query.)

本地库因为历史上该列被旁路 DDL 直接创建过（实测 pg 中两列均存在、类型
user-defined）而侥幸不报错，只有空库踩中。

修复：在本迁移**建分表前**用 `ADD COLUMN IF NOT EXISTS` 补建这两列（可空）。
这样迁移链自洽——建列 → 建分表 → 搬运数据；对已存在该列的库则完全无副作用。
守卫：`test/internal/migration/test_migration_empty_db_smoke.py`。

Revision ID: a3d4e5f6g7b8
Revises: z2c3d4e5f6a7
Create Date: 2026-07-18 21:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a3d4e5f6g7b8"
down_revision = "z2c3d4e5f6a7"
branch_labels = None
depends_on = None

# 本次迁移创建的维度（系统当前使用的维度）
_DIMENSION = 1536


def upgrade() -> None:
    """创建 1536 维向量分表并迁移现有数据。"""
    um_table = f"user_memory_embedding_{_DIMENSION}"
    ks_table = f"knowledge_segment_embedding_{_DIMENSION}"

    # 0. 兜底补建源向量列（见模块 docstring「修复记录」）。
    #    先建列再建分表再搬运，保证空库可跑；对已有该列的库是 no-op。
    op.execute(
        f"ALTER TABLE user_memory "
        f"ADD COLUMN IF NOT EXISTS embedding vector({_DIMENSION})"
    )
    op.execute(
        f"ALTER TABLE knowledge_segment "
        f"ADD COLUMN IF NOT EXISTS embedding vector({_DIMENSION})"
    )

    # 1. 创建 user_memory_embedding_1536 表
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {um_table} (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            memory_id UUID REFERENCES user_memory(id) ON DELETE CASCADE,
            owner_account_id UUID NOT NULL REFERENCES account(id),
            embedding vector({_DIMENSION}) NOT NULL,
            embedding_node_id VARCHAR(255),
            created_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            updated_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0)
        )
    """)
    op.create_index(
        f"{um_table}_owner_idx", um_table, ["owner_account_id"],
        if_not_exists=True,
    )
    op.create_index(
        f"{um_table}_memory_idx", um_table, ["memory_id"],
        if_not_exists=True,
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {um_table}_embedding_hnsw_idx "
        f"ON {um_table} USING hnsw (embedding vector_cosine_ops)"
    )

    # 2. 创建 knowledge_segment_embedding_1536 表
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {ks_table} (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            segment_id UUID NOT NULL REFERENCES knowledge_segment(id) ON DELETE CASCADE,
            knowledge_base_id UUID NOT NULL REFERENCES knowledge_base(id),
            embedding vector({_DIMENSION}) NOT NULL,
            created_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            updated_at TIMESTAMP(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0)
        )
    """)
    op.create_index(
        f"{ks_table}_kb_idx", ks_table, ["knowledge_base_id"],
        if_not_exists=True,
    )
    op.create_index(
        f"{ks_table}_segment_idx", ks_table, ["segment_id"],
        if_not_exists=True,
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {ks_table}_embedding_hnsw_idx "
        f"ON {ks_table} USING hnsw (embedding vector_cosine_ops)"
    )

    # 3. 迁移 user_memory.embedding → user_memory_embedding_1536
    #    仅迁移 embedding 非空且 owner_account_id 非空的记录
    op.execute(f"""
        INSERT INTO {um_table} (memory_id, owner_account_id, embedding, embedding_node_id)
        SELECT id, owner_account_id, embedding, embedding_node_id
        FROM user_memory
        WHERE embedding IS NOT NULL
          AND owner_account_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # 4. 迁移 knowledge_segment.embedding → knowledge_segment_embedding_1536
    op.execute(f"""
        INSERT INTO {ks_table} (segment_id, knowledge_base_id, embedding)
        SELECT ks.id, ks.knowledge_base_id, ks.embedding
        FROM knowledge_segment ks
        WHERE ks.embedding IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    """回滚：删除维度分表（原表 embedding 列数据保留）。"""
    um_table = f"user_memory_embedding_{_DIMENSION}"
    ks_table = f"knowledge_segment_embedding_{_DIMENSION}"

    op.execute(f"DROP TABLE IF EXISTS {um_table} CASCADE")
    op.execute(f"DROP TABLE IF EXISTS {ks_table} CASCADE")
    # 注意：不删除 upgrade 中兜底补建的 embedding 列——该列在 ORM 模型中
    # 仍有声明、且被 memory 检索链路使用，删除会破坏运行时。此处保持列存在。
