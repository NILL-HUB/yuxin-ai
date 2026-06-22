"""upgrade memory system phase f

Revision ID: e1f2a3b4c5d7
Revises: f7a8b9c0d1e2
Create Date: 2026-06-23 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e1f2a3b4c5d7'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('user_memory', sa.Column('embedding_node_id', sa.String(length=255), nullable=True))
    op.add_column('user_memory', sa.Column('scope', sa.String(length=64), server_default=sa.text("'global'::character varying"), nullable=False))
    op.add_column('user_memory', sa.Column('source_conversation_ids', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('user_memory', sa.Column('last_used_at', sa.DateTime(), nullable=True))

    op.add_column('memory_candidate', sa.Column('memory_type', sa.String(length=64), server_default=sa.text("'preference'::character varying"), nullable=False))
    op.add_column('memory_candidate', sa.Column('source_conversation_id', sa.UUID(), nullable=True))
    op.add_column('memory_candidate', sa.Column('extracted_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('memory_candidate', 'extracted_at')
    op.drop_column('memory_candidate', 'source_conversation_id')
    op.drop_column('memory_candidate', 'memory_type')

    op.drop_column('user_memory', 'last_used_at')
    op.drop_column('user_memory', 'source_conversation_ids')
    op.drop_column('user_memory', 'scope')
    op.drop_column('user_memory', 'embedding_node_id')
