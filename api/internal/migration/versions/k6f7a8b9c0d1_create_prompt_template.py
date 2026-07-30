"""create prompt_template table

Revision ID: k6f7a8b9c0d1
Revises: j5e6f7a8b9c0
Create Date: 2026-07-30 06:00:00.000000

变更内容：
新建 prompt_template 表，存储系统级 prompt 模板。
支持 YAML→DB 单向同步（source=catalog）和 admin 自定义（source=custom）。
将指挥官 system prompt 从硬编码迁移到 DB 管理，方便迭代优化。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'k6f7a8b9c0d1'
down_revision = 'j5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'prompt_template',
        sa.Column('prompt_key', sa.String(64), nullable=False),
        sa.Column('name', sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('category', sa.String(64), nullable=False, server_default=sa.text("'general'::character varying")),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('content', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('source', sa.String(32), nullable=False, server_default=sa.text("'catalog'::character varying")),
        sa.Column('source_path', sa.String(512), nullable=True),
        sa.Column('content_hash', sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column('version', sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint('prompt_key', name='pk_prompt_template_key'),
    )
    op.create_index('prompt_template_category_idx', 'prompt_template', ['category'])
    op.create_index('prompt_template_enabled_idx', 'prompt_template', ['enabled'])
    op.create_index('prompt_template_source_idx', 'prompt_template', ['source'])


def downgrade():
    op.drop_index('prompt_template_source_idx', table_name='prompt_template')
    op.drop_index('prompt_template_enabled_idx', table_name='prompt_template')
    op.drop_index('prompt_template_category_idx', table_name='prompt_template')
    op.drop_table('prompt_template')
