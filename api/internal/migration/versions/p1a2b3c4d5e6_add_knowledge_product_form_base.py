"""knowledge product form base

Revision ID: p1a2b3c4d5e6
Revises: o9d0e1f2a3b4
Create Date: 2026-09-12

新增知识库产品形态数据基座：
- knowledge_base 增加 base_type / partition_mode
- knowledge_document 增加 partition_id / media_type / parse_profile
- upload_file.size 由 integer 升级为 bigint
- 新增 knowledge_partition / knowledge_base_tag / knowledge_document_tag / account_storage_usage
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'p1a2b3c4d5e6'
down_revision = 'o9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    # 1) knowledge_base 扩展
    op.add_column('knowledge_base', sa.Column(
        'base_type', sa.String(length=32), nullable=False,
        server_default=sa.text("'mixed'::character varying")))
    op.add_column('knowledge_base', sa.Column(
        'partition_mode', sa.String(length=32), nullable=False,
        server_default=sa.text("'none'::character varying")))
    op.create_index('knowledge_base_base_type_idx', 'knowledge_base', ['base_type'])

    # 2) knowledge_document 扩展
    op.add_column('knowledge_document', sa.Column('partition_id', sa.UUID(), nullable=True))
    op.add_column('knowledge_document', sa.Column(
        'media_type', sa.String(length=32), nullable=False,
        server_default=sa.text("'document'::character varying")))
    op.add_column('knowledge_document', sa.Column(
        'parse_profile', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'{}'::jsonb")))
    op.create_index('knowledge_document_partition_idx', 'knowledge_document', ['partition_id'])
    op.create_index('knowledge_document_media_type_idx', 'knowledge_document', ['media_type'])

    # 3) upload_file.size 升级 bigint（大文件必须）
    op.alter_column('upload_file', 'size',
                    existing_type=sa.Integer(), type_=sa.BigInteger(),
                    existing_nullable=False)

    # 4) knowledge_partition
    op.create_table(
        'knowledge_partition',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('partition_key', sa.String(length=128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('visibility_scope', sa.String(length=64), nullable=False, server_default=sa.text("'private'::character varying")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'],
                                name='fk_knowledge_partition_base_id_knowledge_base', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['knowledge_partition.id'],
                                name='fk_knowledge_partition_parent_id_knowledge_partition', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_partition_id'),
        sa.UniqueConstraint('knowledge_base_id', 'partition_key', name='uq_knowledge_partition_base_key'),
    )
    op.create_index('knowledge_partition_parent_id_idx', 'knowledge_partition', ['parent_id'])
    op.create_index('knowledge_partition_sort_idx', 'knowledge_partition', ['knowledge_base_id', 'sort_order'])

    # 4.1) knowledge_document.partition_id 外键（需等 knowledge_partition 建表后追加）
    op.create_foreign_key(
        'fk_knowledge_document_partition_id_knowledge_partition',
        'knowledge_document', 'knowledge_partition',
        ['partition_id'], ['id'], ondelete='SET NULL')

    # 5) knowledge_base_tag
    op.create_table(
        'knowledge_base_tag',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'],
                                name='fk_knowledge_base_tag_base_id_knowledge_base', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'],
                                name='fk_knowledge_base_tag_tag_id_tag', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_base_tag_id'),
        sa.UniqueConstraint('knowledge_base_id', 'tag_id', name='uq_knowledge_base_tag_pair'),
    )
    op.create_index('knowledge_base_tag_tag_idx', 'knowledge_base_tag', ['tag_id'])
    op.create_index('knowledge_base_tag_account_idx', 'knowledge_base_tag', ['account_id'])

    # 6) knowledge_document_tag
    op.create_table(
        'knowledge_document_tag',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('knowledge_document_id', sa.UUID(), nullable=False),
        sa.Column('tag_id', sa.UUID(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['knowledge_document_id'], ['knowledge_document.id'],
                                name='fk_knowledge_document_tag_document_id_knowledge_document', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'],
                                name='fk_knowledge_document_tag_tag_id_tag', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_document_tag_id'),
        sa.UniqueConstraint('knowledge_document_id', 'tag_id', name='uq_knowledge_document_tag_pair'),
    )
    op.create_index('knowledge_document_tag_tag_idx', 'knowledge_document_tag', ['tag_id'])
    op.create_index('knowledge_document_tag_account_idx', 'knowledge_document_tag', ['account_id'])

    # 7) account_storage_usage
    op.create_table(
        'account_storage_usage',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('used_bytes', sa.BigInteger(), nullable=False, server_default=sa.text('0')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'],
                                name='fk_account_storage_usage_account_id_account', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='pk_account_storage_usage_id'),
        sa.UniqueConstraint('account_id', name='uq_account_storage_usage_account_id'),
    )


def downgrade():
    op.drop_table('account_storage_usage')

    op.drop_index('knowledge_document_tag_account_idx', table_name='knowledge_document_tag')
    op.drop_index('knowledge_document_tag_tag_idx', table_name='knowledge_document_tag')
    op.drop_table('knowledge_document_tag')

    op.drop_index('knowledge_base_tag_account_idx', table_name='knowledge_base_tag')
    op.drop_index('knowledge_base_tag_tag_idx', table_name='knowledge_base_tag')
    op.drop_table('knowledge_base_tag')

    # 先解除 knowledge_document 对分区的外键引用，再删分区表（避免依赖冲突）
    op.drop_constraint('fk_knowledge_document_partition_id_knowledge_partition',
                       'knowledge_document', type_='foreignkey')
    op.drop_index('knowledge_document_media_type_idx', table_name='knowledge_document')
    op.drop_index('knowledge_document_partition_idx', table_name='knowledge_document')
    op.drop_column('knowledge_document', 'parse_profile')
    op.drop_column('knowledge_document', 'media_type')
    op.drop_column('knowledge_document', 'partition_id')

    op.drop_index('knowledge_partition_sort_idx', table_name='knowledge_partition')
    op.drop_index('knowledge_partition_parent_id_idx', table_name='knowledge_partition')
    op.drop_table('knowledge_partition')

    op.alter_column('upload_file', 'size',
                    existing_type=sa.BigInteger(), type_=sa.Integer(),
                    existing_nullable=False)

    op.drop_index('knowledge_base_base_type_idx', table_name='knowledge_base')
    op.drop_column('knowledge_base', 'partition_mode')
    op.drop_column('knowledge_base', 'base_type')
