# api/internal/migration/versions/a3d4e5f6g7b8_create_embedding_dim_tables_and_migrate.py
"""create embedding dimension tables and migrate existing vectors

创建按维度分表的向量存储表（1536 维），并将 user_memory.embedding 和
knowledge_segment.embedding 中的现有向量迁移到新表。

按维度分表架构：
    - user_memory_embedding_{dim}: 存储 user_memory 的向量（按维度分表）
    - knowledge_segment_embedding_{dim}: 存储 knowledge_segment 的向量（按维度分表）
    - 原表的 embedding 列保留但不再使用（后续迁移中废弃）

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
