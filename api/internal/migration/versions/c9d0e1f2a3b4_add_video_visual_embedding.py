"""add video_visual_embedding table

Revision ID: c9d0e1f2a3b4
Revises: q2b3c4d5e6f7
Create Date: 2026-09-15

变更内容：
新建 video_visual_embedding 表，存储视频关键帧的视觉向量，支撑以图搜图与
跨模态（文本 query 直接召回画面）检索。

维度固定 1536：Qwen3-VL-Embedding-8B 原生 4096 维超出 pgvector 的 vector
类型上限 2000，经 MRL 降维到 1536（本项目主维度）。

注意：down_revision 必须指向**已提交**的迁移。历史上曾指向未纳入版本控制的
revision，导致全新 clone / CI 上 alembic upgrade head 崩溃；
test/internal/migration/test_migration_graph_integrity.py 对此设有守卫。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = 'c9d0e1f2a3b4'
down_revision = 'q2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'video_visual_embedding',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('knowledge_base_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('knowledge_document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('segment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('frame_url', sa.String(512), nullable=False,
                  server_default=sa.text("''::character varying")),
        sa.Column('scene_index', sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column('model_id', sa.String(36), nullable=True),
        sa.Column('embedding', Vector(1536), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint('id', name='pk_video_visual_embedding_id'),
        sa.UniqueConstraint('segment_id', name='uq_video_visual_embedding_segment'),
    )
    # 外键单独添加：downgrade 时随表删除即可，无需单独 drop_constraint
    op.create_foreign_key(
        'fk_video_visual_embedding_kb', 'video_visual_embedding', 'knowledge_base',
        ['knowledge_base_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_video_visual_embedding_doc', 'video_visual_embedding', 'knowledge_document',
        ['knowledge_document_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_video_visual_embedding_seg', 'video_visual_embedding', 'knowledge_segment',
        ['segment_id'], ['id'], ondelete='CASCADE',
    )
    op.create_index('video_visual_embedding_kb_idx', 'video_visual_embedding',
                    ['knowledge_base_id'])
    op.create_index('video_visual_embedding_document_idx', 'video_visual_embedding',
                    ['knowledge_document_id'])
    op.create_index('video_visual_embedding_account_idx', 'video_visual_embedding',
                    ['account_id'])
    # HNSW 余弦索引：帧数量随视频量增长，需要 ANN 索引而非全表顺序扫描
    op.execute(
        "CREATE INDEX IF NOT EXISTS video_visual_embedding_hnsw_idx "
        "ON video_visual_embedding USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade():
    op.drop_table('video_visual_embedding')
