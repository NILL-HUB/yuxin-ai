"""knowledge product form base

Revision ID: p1a2b3c4d5e6
Revises: n8c9d0e1f2a3
Create Date: 2026-09-12

新增知识库产品形态数据基座：
- knowledge_base 增加 base_type / partition_mode
- knowledge_document 增加 partition_id / media_type / parse_profile
- upload_file.size 由 integer 升级为 bigint
- 新增 knowledge_partition / knowledge_base_tag / knowledge_document_tag / account_storage_usage
- （修复）补建 tag / app_tag / workflow_tag

注意一：本迁移的 down_revision 必须是**已提交**的迁移（此处为 `n8c9d0e1f2a3`）。
曾误指向未纳入版本控制的 `o9d0e1f2a3b4`，导致全新 clone / CI 上
`alembic upgrade head` 因 "Revision ... is not present" 崩溃。
若后续 `o9d0e1f2a3b4` 被提交，会与本迁移形成两个 head，必须补一个 merge 迁移
（参见 test/internal/migration/test_migration_graph_integrity.py）。

注意二（修复记录，2026-09 空库验证）：本迁移第 5/6 步建
`knowledge_base_tag` / `knowledge_document_tag`，带外键 `REFERENCES tag (id)`，
但 `tag` 表在**迁移链中从未被创建**（历史上经 `Base.metadata.create_all()` 或
手工 DDL 建出，未落进迁移；真实库中该表确实存在，故本地长期未暴露）。
空库上 `alembic upgrade head` 抛：

    relation "tag" does not exist
    CREATE TABLE knowledge_base_tag ( ... FOREIGN KEY(tag_id) REFERENCES tag (id) ... )

修复选择「就地补建」而非「插入新迁移」：`tag` 的**唯一**引用点就是本迁移
（`app_tag` / `workflow_tag` 的模型未声明外键，无顺序约束），在本迁移开头用
`CREATE TABLE IF NOT EXISTS` 建出即可，既保证顺序又**不动迁移图**（不多一个
head、不新增 revision）。对已应用本迁移的库是 no-op（表早已存在）。
守卫：test/internal/migration/test_migration_empty_db_smoke.py。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'p1a2b3c4d5e6'
down_revision = 'n8c9d0e1f2a3'
branch_labels = None
depends_on = None


def upgrade():
    # 0) 兜底补建 tag / app_tag / workflow_tag（见模块 docstring「注意二」）。
    #    必须在第 5) 步建 knowledge_base_tag（外键 REFERENCES tag(id)）之前。
    #    对已存在这些表的库是 no-op（IF NOT EXISTS）。
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tag (
            id UUID NOT NULL DEFAULT uuid_generate_v4(),
            account_id UUID NOT NULL,
            name VARCHAR(50) NOT NULL,
            description TEXT DEFAULT ''::text,
            tag_type VARCHAR(50) NOT NULL DEFAULT 'custom',
            status VARCHAR(50) NOT NULL DEFAULT 'active',
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            CONSTRAINT pk_tag_id PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS tag_account_id_idx ON tag (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS tag_status_idx ON tag (status)")
    op.execute("CREATE INDEX IF NOT EXISTS tag_type_idx ON tag (tag_type)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_tag (
            id UUID NOT NULL DEFAULT uuid_generate_v4(),
            account_id UUID NOT NULL,
            app_id UUID NOT NULL,
            tag_id UUID NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            CONSTRAINT pk_app_tag_id PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS app_tag_app_id_idx ON app_tag (app_id)")
    op.execute("CREATE INDEX IF NOT EXISTS app_tag_tag_id_idx ON app_tag (tag_id)")
    op.execute("CREATE INDEX IF NOT EXISTS app_tag_account_id_idx ON app_tag (account_id)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_tag (
            id UUID NOT NULL DEFAULT uuid_generate_v4(),
            account_id UUID NOT NULL,
            workflow_id UUID NOT NULL,
            tag_id UUID NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
            CONSTRAINT pk_workflow_tag_id PRIMARY KEY (id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workflow_tag_workflow_id_idx ON workflow_tag (workflow_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workflow_tag_tag_id_idx ON workflow_tag (tag_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workflow_tag_account_id_idx ON workflow_tag (account_id)"
    )

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
