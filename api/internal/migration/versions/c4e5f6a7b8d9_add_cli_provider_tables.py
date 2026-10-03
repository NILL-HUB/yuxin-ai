"""add cli_provider and cli_tool tables

Revision ID: c4e5f6a7b8d9
Revises: p2c3d4e5f6a8
Create Date: 2026-10-03 00:00:00.000000

变更内容：
新增 cli_provider / cli_tool 两张表及其索引，用于登记纯 CLI 工具提供者
与工具元数据（工具粒度，1:N 关联）。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'c4e5f6a7b8d9'
down_revision = 'p2c3d4e5f6a8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'cli_provider',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('label', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('icon', sa.String(512), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('category', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('command', sa.String(1024), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('env', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('tool_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('task_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('is_public', sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column('source_type', sa.String(64), nullable=False, server_default=sa.text("'cli'::character varying")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)"), server_onupdate=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(['account_id'], ['account.id']),
        sa.PrimaryKeyConstraint('id', name='pk_cli_provider_id'),
    )
    op.create_index('cli_provider_account_id_idx', 'cli_provider', ['account_id'])
    op.create_index('cli_provider_is_public_idx', 'cli_provider', ['is_public'])
    op.create_index('cli_provider_task_keywords_idx', 'cli_provider', ['task_keywords'], postgresql_using='gin')

    op.create_table(
        'cli_tool',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('provider_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('input_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('task_keywords', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.ForeignKeyConstraint(['provider_id'], ['cli_provider.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_cli_tool_id'),
    )
    op.create_index('cli_tool_provider_id_idx', 'cli_tool', ['provider_id'])
    op.create_index('cli_tool_name_idx', 'cli_tool', ['name'])
    op.create_index('cli_tool_task_keywords_idx', 'cli_tool', ['task_keywords'], postgresql_using='gin')


def downgrade():
    op.drop_index('cli_tool_task_keywords_idx', table_name='cli_tool')
    op.drop_index('cli_tool_name_idx', table_name='cli_tool')
    op.drop_index('cli_tool_provider_id_idx', table_name='cli_tool')
    op.drop_table('cli_tool')
    op.drop_index('cli_provider_task_keywords_idx', table_name='cli_provider')
    op.drop_index('cli_provider_is_public_idx', table_name='cli_provider')
    op.drop_index('cli_provider_account_id_idx', table_name='cli_provider')
    op.drop_table('cli_provider')
