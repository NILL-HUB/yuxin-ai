"""add billing usage event and reconciliation tables

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-30 08:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'e8f9a0b1c2d3'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'billing_usage_event',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('task_id', sa.String(length=128), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('model_id', sa.String(length=64), nullable=True),
        sa.Column('source_type', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('input_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('output_tokens', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('billing_basis', sa.String(length=64), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('is_estimated', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('estimated_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('actual_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_billing_usage_event_id'),
    )
    op.create_index('billing_usage_event_task_idx', 'billing_usage_event', ['task_id'])
    op.create_index('billing_usage_event_model_idx', 'billing_usage_event', ['model_id'])
    op.create_index('billing_usage_event_created_idx', 'billing_usage_event', ['created_at'])

    op.create_table(
        'billing_reconciliation',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('task_id', sa.String(length=128), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('estimated_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('actual_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('diff_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('cost_amount', sa.Numeric(precision=12, scale=6), server_default=sa.text('0.000000'), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'settled'::character varying"), nullable=False),
        sa.Column('alert_flags', JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('settled_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_billing_reconciliation_id'),
    )
    op.create_index('billing_reconciliation_task_idx', 'billing_reconciliation', ['task_id'], unique=True)
    op.create_index('billing_reconciliation_account_idx', 'billing_reconciliation', ['account_id'])


def downgrade():
    op.drop_index('billing_reconciliation_account_idx', table_name='billing_reconciliation')
    op.drop_index('billing_reconciliation_task_idx', table_name='billing_reconciliation')
    op.drop_table('billing_reconciliation')
    op.drop_index('billing_usage_event_created_idx', table_name='billing_usage_event')
    op.drop_index('billing_usage_event_model_idx', table_name='billing_usage_event')
    op.drop_index('billing_usage_event_task_idx', table_name='billing_usage_event')
    op.drop_table('billing_usage_event')