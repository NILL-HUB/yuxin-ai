"""drop resource_vector_index table

Revision ID: p2c3d4e5f6a8
Revises: o9f0a1b2c3d4
Create Date: 2026-09-30 00:00:00.000000

变更内容：
删除 resource_vector_index 表及其索引。

该表原用于两处向量语义检索，现已全部下线：
- 指挥官模型摘要：改为直查 model_pool_config（实时数据，无快照漂移）；
- Agent 工具选择：统一走 ToolSelectorService（关键词快通道 + LLM 语义兜底），
  不依赖向量索引表，覆盖 builtin/api_tool/mcp/skill/workflow/knowledge 全类型。

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = 'p2c3d4e5f6a8'
down_revision = 'o9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS resource_vector_index_enabled_idx")
    op.execute("DROP INDEX IF EXISTS resource_vector_index_sub_pool_idx")
    op.execute("DROP INDEX IF EXISTS resource_vector_index_type_idx")
    op.execute("DROP TABLE IF EXISTS resource_vector_index")


def downgrade():
    op.create_table(
        'resource_vector_index',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('resource_type', sa.String(32), nullable=False),
        sa.Column('resource_id', sa.String(64), nullable=False),
        sa.Column('resource_name', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('capabilities', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('sub_pool', sa.String(64), nullable=False, server_default=sa.text("'general'::character varying")),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('embedding_model_id', sa.String(64), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint('id', name='pk_resource_vector_index_id'),
        sa.UniqueConstraint('resource_type', 'resource_id', name='uq_resource_vector_index_type_id'),
    )
    op.create_index('resource_vector_index_type_idx', 'resource_vector_index', ['resource_type'])
    op.create_index('resource_vector_index_sub_pool_idx', 'resource_vector_index', ['sub_pool'])
    op.create_index('resource_vector_index_enabled_idx', 'resource_vector_index', ['enabled'])
