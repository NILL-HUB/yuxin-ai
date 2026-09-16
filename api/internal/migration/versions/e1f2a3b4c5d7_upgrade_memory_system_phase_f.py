"""upgrade memory system phase f

Revision ID: e1f2a3b4c5d7
Revises: f7a8b9c0d1e2, d1e2f3a4b5c7
Create Date: 2026-06-23 00:00:00.000000

本迁移给 `user_memory` / `memory_candidate` 加列。

**为什么 down_revision 是两个（本次修复）**：
原值仅为 `f7a8b9c0d1e2`（兑换码批次支线），但本迁移实际依赖
`d1e2f3a4b5c7`（建 `user_memory` 与 `memory_candidate` 的迁移，挂在
`c0d1e2f3a4b5` 支线上）。两条支线直到 `f2a3b4c5d6e8` 才合并，因此对 alembic
而言二者**无先后约束**，按拓扑序可能在建表之前就执行本迁移。

实测后果（2026-09，空库验证）：全新数据库执行 `alembic upgrade head` 跑到
第 38 条即本迁移时崩溃——

    relation "user_memory" does not exist
    [SQL: ALTER TABLE user_memory ADD COLUMN embedding_node_id VARCHAR(255)]

影响面：`docker/entrypoint.sh` 在 `MIGRATION_ENABLED=true` 时自动执行
`alembic upgrade head`，故**生产首次部署、新建 staging、CI 全新 clone** 全部受阻。
本地库因为是历史**增量**应用（`d1e2f3a4b5c7` 当年早已执行过）而侥幸不报错，
只有空库才会暴露。

修复：把 `d1e2f3a4b5c7` 补入 down_revision，使其成为显式合并点，强制建表迁移
先执行。已应用过本迁移的库无需重跑（`alembic_version` 不回退）。
守卫：`test/internal/migration/test_migration_empty_db_smoke.py`。

参考先例：`p1a2b3c4d5e6` 亦曾通过调整 down_revision 修复迁移链。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e1f2a3b4c5d7'
down_revision = ('f7a8b9c0d1e2', 'd1e2f3a4b5c7')
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_memory', sa.Column('embedding_node_id', sa.String(length=255), nullable=True))
    op.add_column('user_memory', sa.Column('scope', sa.String(length=64), server_default=sa.text("'global'::character varying"), nullable=False))
    op.add_column('user_memory', sa.Column('source_conversation_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('user_memory', sa.Column('last_used_at', sa.DateTime(), nullable=True))

    op.add_column('memory_candidate', sa.Column('memory_type', sa.String(length=64), server_default=sa.text("'preference'::character varying"), nullable=False))
    op.add_column('memory_candidate', sa.Column('source_conversation_id', sa.UUID(), nullable=True))
    op.add_column('memory_candidate', sa.Column('extracted_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('memory_candidate', 'extracted_at')
    op.drop_column('memory_candidate', 'source_conversation_id')
    op.drop_column('memory_candidate', 'memory_type')

    op.drop_column('user_memory', 'last_used_at')
    op.drop_column('user_memory', 'source_conversation_ids')
    op.drop_column('user_memory', 'scope')
    op.drop_column('user_memory', 'embedding_node_id')
