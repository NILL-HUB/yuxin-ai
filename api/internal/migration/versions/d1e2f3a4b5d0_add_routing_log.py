"""add routing log

Revision ID: d1e2f3a4b5d0
Revises: d1e2f3a4b5c9
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5d0'
down_revision = 'd1e2f3a4b5c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'routing_log',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.Column('routing_decision', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('agent_candidates', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('filtered_out_agents', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('tool_candidates', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('filtered_out_tools', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('knowledge_hits', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('billing_events', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'success'::character varying"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], name='fk_routing_log_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_routing_log_id'),
    )
    op.create_index('routing_log_account_id_idx', 'routing_log', ['account_id'])
    op.create_index('routing_log_message_id_idx', 'routing_log', ['message_id'])
    op.create_index('routing_log_status_idx', 'routing_log', ['status'])


def downgrade():
    op.drop_index('routing_log_status_idx', table_name='routing_log')
    op.drop_index('routing_log_message_id_idx', table_name='routing_log')
    op.drop_index('routing_log_account_id_idx', table_name='routing_log')
    op.drop_table('routing_log')
