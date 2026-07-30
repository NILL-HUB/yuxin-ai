"""add mcp_tool table and output_schema to api_tool/builtin_tool

Revision ID: h3c4d5e6f7a8
Revises: g2b3c4d5e6f7
Create Date: 2026-07-30 02:00:00.000000

变更内容：
1. 新建 mcp_tool 表：存储 MCP 工具粒度元数据（name/description/input_schema/output_schema），
   供向量索引和关键词检索使用。与 mcp_provider 1:N 关联。
2. 为 api_tool 表新增 output_schema 字段：用于 Agent 选择工具时判断输出形态。
3. 为 builtin_tool 表新增 output_schema 字段：同上。

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'h3c4d5e6f7a8'
down_revision = 'g2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade():
    # 1. 新建 mcp_tool 表
    op.create_table(
        'mcp_tool',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('title', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('annotations', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('task_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('schema_hash', sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('sync_status', sa.String(64), nullable=False, server_default=sa.text("'pending'::character varying")),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint('id', name='pk_mcp_tool_id'),
        sa.ForeignKeyConstraint(['provider_id'], ['mcp_provider.id'], ondelete='CASCADE'),
    )
    op.create_index('mcp_tool_provider_id_idx', 'mcp_tool', ['provider_id'])
    op.create_index('mcp_tool_name_idx', 'mcp_tool', ['name'])
    op.create_index('mcp_tool_enabled_idx', 'mcp_tool', ['enabled'])
    op.create_index('mcp_tool_task_keywords_idx', 'mcp_tool', ['task_keywords'], postgresql_using='gin')

    # 2. 为 api_tool 表新增 output_schema 字段
    op.add_column(
        'api_tool',
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # 3. 为 builtin_tool 表新增 output_schema 字段
    op.add_column(
        'builtin_tool',
        sa.Column('output_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade():
    # 回滚 api_tool / builtin_tool 的 output_schema
    op.drop_column('builtin_tool', 'output_schema')
    op.drop_column('api_tool', 'output_schema')

    # 回滚 mcp_tool 表
    op.drop_index('mcp_tool_task_keywords_idx', table_name='mcp_tool')
    op.drop_index('mcp_tool_enabled_idx', table_name='mcp_tool')
    op.drop_index('mcp_tool_name_idx', table_name='mcp_tool')
    op.drop_index('mcp_tool_provider_id_idx', table_name='mcp_tool')
    op.drop_table('mcp_tool')
