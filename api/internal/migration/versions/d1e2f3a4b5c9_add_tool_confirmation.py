"""add tool confirmation

Revision ID: d1e2f3a4b5c9
Revises: d1e2f3a4b5c8
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5c9'
down_revision = 'd1e2f3a4b5c8'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tool_confirmation',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('owner_account_id', sa.UUID(), nullable=False),
        sa.Column('tool_name', sa.String(length=255), nullable=False),
        sa.Column('risk_level', sa.String(length=64), server_default=sa.text("'high'::character varying"), nullable=False),
        sa.Column('tool_input', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('status', sa.String(length=64), server_default=sa.text("'pending'::character varying"), nullable=False),
        sa.Column('spent_credits', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('reason', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['owner_account_id'], ['account.id'], name='fk_tool_confirmation_owner_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_tool_confirmation_id'),
    )
    op.create_index('tool_confirmation_owner_status_idx', 'tool_confirmation', ['owner_account_id', 'status'])
    op.create_index('tool_confirmation_tool_name_idx', 'tool_confirmation', ['tool_name'])


def downgrade():
    op.drop_index('tool_confirmation_tool_name_idx', table_name='tool_confirmation')
    op.drop_index('tool_confirmation_owner_status_idx', table_name='tool_confirmation')
    op.drop_table('tool_confirmation')
