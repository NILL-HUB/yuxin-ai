"""create resource_vector_index table

Revision ID: j5e6f7a8b9c0
Revises: i4d5e6f7a8b9
Create Date: 2026-07-30 04:00:00.000000

变更内容：
新建 resource_vector_index 表，统一存储模型/MCP工具/Skill/内置工具/API工具的向量索引。
供指挥官（选模型）和 Agent（选工具）做语义检索。

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = 'j5e6f7a8b9c0'
down_revision = 'i4d5e6f7a8b9'
branch_labels = None
depends_on = None


def upgrade():
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


def downgrade():
    op.drop_index('resource_vector_index_enabled_idx', table_name='resource_vector_index')
    op.drop_index('resource_vector_index_sub_pool_idx', table_name='resource_vector_index')
    op.drop_index('resource_vector_index_type_idx', table_name='resource_vector_index')
    op.drop_table('resource_vector_index')
