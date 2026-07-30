"""drop memory_candidate table

Revision ID: s3d4e5f6a7b8
Revises: r2c3d4e5f6a7
Create Date: 2026-07-10 00:00:00.000000

记忆系统重构后，候选记忆确认流程已被自动写入替代，
memory_candidate 表不再使用，安全删除。
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 's3d4e5f6a7b8'
down_revision = 'r2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table('memory_candidate')


def downgrade():
    op.create_table(
        'memory_candidate',
        sa.Column('id', UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('owner_account_id', UUID(), sa.ForeignKey('account.id'), nullable=False),
        sa.Column('candidate_key', sa.String(255), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('content', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('confidence', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('occurrences', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('status', sa.String(64), nullable=False, server_default=sa.text("'pending'::character varying")),
        sa.Column('memory_type', sa.String(64), nullable=False, server_default=sa.text("'preference'::character varying")),
        sa.Column('scope', sa.String(64), nullable=False, server_default=sa.text("'global'::character varying")),
        sa.Column('source_conversation_id', UUID(), nullable=True),
        sa.Column('extracted_at', sa.DateTime(), nullable=True),
        sa.Column('save_reason', sa.Text(), nullable=True),
        sa.Column('metadata', JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.PrimaryKeyConstraint('id', name='pk_memory_candidate_id'),
    )
    op.create_index('memory_candidate_owner_key_idx', 'memory_candidate', ['owner_account_id', 'candidate_key'])
    op.create_index('memory_candidate_status_idx', 'memory_candidate', ['status'])
