# api/internal/migration/versions/e9f0a1b2c3d4_add_unique_constraints_to_embedding_tables.py
"""add unique constraints to embedding tables

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-07-22 15:00:00.000000

为向量分表添加 UNIQUE 约束，修复 ON CONFLICT upsert 失败问题。
user_memory_embedding_{dim}.memory_id 和 knowledge_segment_embedding_{dim}.segment_id 缺少唯一约束。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e9f0a1b2c3d4"
down_revision = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 动态发现所有已存在的维度分表，为它们添加 UNIQUE 约束
    bind = op.get_bind()

    # 查找所有 user_memory_embedding_* 表
    result = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'user_memory_embedding_%' AND table_schema = 'public'"
    ))
    um_tables = [row[0] for row in result]

    for table_name in um_tables:
        # 先清理可能的重复数据（保留最新一条，即 id 更大的）
        bind.execute(sa.text(f"""
            DELETE FROM {table_name} a USING {table_name} b
            WHERE a.id < b.id AND a.memory_id = b.memory_id AND a.memory_id IS NOT NULL
        """))
        # 添加 UNIQUE 索引
        bind.execute(sa.text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_memory_id_uidx "
            f"ON {table_name} (memory_id)"
        ))

    # 查找所有 knowledge_segment_embedding_* 表
    result = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'knowledge_segment_embedding_%' AND table_schema = 'public'"
    ))
    ks_tables = [row[0] for row in result]

    for table_name in ks_tables:
        # 先清理可能的重复数据
        bind.execute(sa.text(f"""
            DELETE FROM {table_name} a USING {table_name} b
            WHERE a.id < b.id AND a.segment_id = b.segment_id AND a.segment_id IS NOT NULL
        """))
        # 添加 UNIQUE 索引
        bind.execute(sa.text(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {table_name}_segment_id_uidx "
            f"ON {table_name} (segment_id)"
        ))


def downgrade() -> None:
    bind = op.get_bind()

    # 删除 user_memory_embedding_* 表的 UNIQUE 索引
    result = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'user_memory_embedding_%' AND table_schema = 'public'"
    ))
    for row in result:
        table_name = row[0]
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {table_name}_memory_id_uidx"))

    # 删除 knowledge_segment_embedding_* 表的 UNIQUE 索引
    result = bind.execute(sa.text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name LIKE 'knowledge_segment_embedding_%' AND table_schema = 'public'"
    ))
    for row in result:
        table_name = row[0]
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {table_name}_segment_id_uidx"))
