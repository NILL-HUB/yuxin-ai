"""add phase1 knowledge memory models

Revision ID: d1e2f3a4b5c7
Revises: c0d1e2f3a4b5
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5c7'
down_revision = 'c0d1e2f3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'knowledge_base',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('description', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('knowledge_scope', sa.String(length=64), server_default=sa.text("'user_content'::character varying"), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=True),
        sa.Column('owner_admin_user_id', sa.UUID(), nullable=True),
        sa.Column('operation_context', sa.String(length=64), server_default=sa.text("'user'::character varying"), nullable=False),
        sa.Column('visibility_scope', sa.String(length=64), server_default=sa.text("'private'::character varying"), nullable=False),
        sa.Column('target_tenant_id', sa.UUID(), nullable=True),
        sa.Column('target_project_id', sa.UUID(), nullable=True),
        sa.Column('created_from', sa.String(length=64), server_default=sa.text("'manual_upload'::character varying"), nullable=False),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_knowledge_base_owner_account_id_account'),
        sa.ForeignKeyConstraint(['owner_admin_user_id'], ['admin_user.id'], name='fk_knowledge_base_owner_admin_user_id_admin_user'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_base_id'),
    )
    op.create_index('knowledge_base_owner_account_scope_idx', 'knowledge_base', ['owner_account_id', 'knowledge_scope'])
    op.create_index('knowledge_base_owner_admin_scope_idx', 'knowledge_base', ['owner_admin_user_id', 'knowledge_scope'])
    op.create_index('knowledge_base_scope_idx', 'knowledge_base', ['knowledge_scope'])
    op.create_index('knowledge_base_target_project_idx', 'knowledge_base', ['target_project_id'])
    op.create_index('knowledge_base_target_tenant_idx', 'knowledge_base', ['target_tenant_id'])

    op.create_table(
        'knowledge_document',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('content_type', sa.String(length=64), server_default=sa.text("'document'::character varying"), nullable=False),
        sa.Column('source_type', sa.String(length=64), server_default=sa.text("'manual_upload'::character varying"), nullable=False),
        sa.Column('source_id', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('upload_file_id', sa.UUID(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('character_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'waiting'::character varying"), nullable=False),
        sa.Column('error', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'], name='fk_knowledge_document_knowledge_base_id_knowledge_base'),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_knowledge_document_owner_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_document_id'),
    )
    op.create_index('knowledge_document_base_id_idx', 'knowledge_document', ['knowledge_base_id'])
    op.create_index('knowledge_document_owner_account_idx', 'knowledge_document', ['owner_account_id'])
    op.create_index('knowledge_document_source_idx', 'knowledge_document', ['source_type', 'source_id'])
    op.create_index('knowledge_document_status_idx', 'knowledge_document', ['status'])

    op.create_table(
        'knowledge_segment',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=False),
        sa.Column('knowledge_document_id', sa.UUID(), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=True),
        sa.Column('position', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('content', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('keywords', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('character_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('token_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('hit_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'waiting'::character varying"), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'], name='fk_knowledge_segment_knowledge_base_id_knowledge_base'),
        sa.ForeignKeyConstraint(['knowledge_document_id'], ['knowledge_document.id'], name='fk_knowledge_segment_knowledge_document_id_knowledge_document'),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_knowledge_segment_owner_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_knowledge_segment_id'),
    )
    op.create_index('knowledge_segment_base_id_idx', 'knowledge_segment', ['knowledge_base_id'])
    op.create_index('knowledge_segment_document_id_idx', 'knowledge_segment', ['knowledge_document_id'])
    op.create_index('knowledge_segment_owner_account_idx', 'knowledge_segment', ['owner_account_id'])
    op.create_index('knowledge_segment_status_idx', 'knowledge_segment', ['status'])

    op.create_table(
        'user_memory',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=False),
        sa.Column('memory_type', sa.String(length=64), server_default=sa.text("'preference'::character varying"), nullable=False),
        sa.Column('content', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('confidence', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('created_from', sa.String(length=64), server_default=sa.text("'conversation_memory'::character varying"), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_user_memory_owner_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_user_memory_id'),
    )
    op.create_index('user_memory_owner_type_idx', 'user_memory', ['owner_account_id', 'memory_type'])
    op.create_index('user_memory_status_idx', 'user_memory', ['status'])

    op.create_table(
        'memory_candidate',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=False),
        sa.Column('candidate_key', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('content', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('confidence', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('occurrences', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_memory_candidate_owner_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_memory_candidate_id'),
    )
    op.create_index('memory_candidate_owner_key_idx', 'memory_candidate', ['owner_account_id', 'candidate_key'])
    op.create_index('memory_candidate_status_idx', 'memory_candidate', ['status'])

    op.create_table(
        'external_data_source',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=True),
        sa.Column('owner_admin_user_id', sa.UUID(), nullable=True),
        sa.Column('knowledge_base_id', sa.UUID(), nullable=True),
        sa.Column('source_type', sa.String(length=64), nullable=False),
        sa.Column('source_name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('authorization_status', sa.String(length=64), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('sync_status', sa.String(length=64), server_default=sa.text("'idle'::character varying"), nullable=False),
        sa.Column('sync_cursor', sa.String(length=1024), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['knowledge_base_id'], ['knowledge_base.id'], name='fk_external_data_source_knowledge_base_id_knowledge_base'),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_external_data_source_owner_account_id_account'),
        sa.ForeignKeyConstraint(['owner_admin_user_id'], ['admin_user.id'], name='fk_external_data_source_owner_admin_user_id_admin_user'),
        sa.PrimaryKeyConstraint('id', name='pk_external_data_source_id'),
    )
    op.create_index('external_data_source_auth_status_idx', 'external_data_source', ['authorization_status'])
    op.create_index('external_data_source_base_id_idx', 'external_data_source', ['knowledge_base_id'])
    op.create_index('external_data_source_owner_type_idx', 'external_data_source', ['owner_account_id', 'source_type'])
    op.create_index('external_data_source_sync_status_idx', 'external_data_source', ['sync_status'])


def downgrade():
    op.drop_index('external_data_source_sync_status_idx', table_name='external_data_source')
    op.drop_index('external_data_source_owner_type_idx', table_name='external_data_source')
    op.drop_index('external_data_source_base_id_idx', table_name='external_data_source')
    op.drop_index('external_data_source_auth_status_idx', table_name='external_data_source')
    op.drop_table('external_data_source')
    op.drop_index('memory_candidate_status_idx', table_name='memory_candidate')
    op.drop_index('memory_candidate_owner_key_idx', table_name='memory_candidate')
    op.drop_table('memory_candidate')
    op.drop_index('user_memory_status_idx', table_name='user_memory')
    op.drop_index('user_memory_owner_type_idx', table_name='user_memory')
    op.drop_table('user_memory')
    op.drop_index('knowledge_segment_status_idx', table_name='knowledge_segment')
    op.drop_index('knowledge_segment_owner_account_idx', table_name='knowledge_segment')
    op.drop_index('knowledge_segment_document_id_idx', table_name='knowledge_segment')
    op.drop_index('knowledge_segment_base_id_idx', table_name='knowledge_segment')
    op.drop_table('knowledge_segment')
    op.drop_index('knowledge_document_status_idx', table_name='knowledge_document')
    op.drop_index('knowledge_document_source_idx', table_name='knowledge_document')
    op.drop_index('knowledge_document_owner_account_idx', table_name='knowledge_document')
    op.drop_index('knowledge_document_base_id_idx', table_name='knowledge_document')
    op.drop_table('knowledge_document')
    op.drop_index('knowledge_base_target_tenant_idx', table_name='knowledge_base')
    op.drop_index('knowledge_base_target_project_idx', table_name='knowledge_base')
    op.drop_index('knowledge_base_scope_idx', table_name='knowledge_base')
    op.drop_index('knowledge_base_owner_admin_scope_idx', table_name='knowledge_base')
    op.drop_index('knowledge_base_owner_account_scope_idx', table_name='knowledge_base')
    op.drop_table('knowledge_base')
