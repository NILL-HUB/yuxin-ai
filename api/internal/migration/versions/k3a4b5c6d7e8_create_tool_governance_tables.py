"""create tool_governance_policy and tool_invocation_audit tables

Revision ID: k3a4b5c6d7e8
Revises: j6k7l8m9n0o1
Create Date: 2026-07-02 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'k3a4b5c6d7e8'
down_revision = 'j6k7l8m9n0o1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tool_governance_policy',
        sa.Column('id', sa.UUID, nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('tool_id', sa.String(128), nullable=False),
        sa.Column('tool_name', sa.String(256), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('source_type', sa.String(64), nullable=False, server_default=sa.text("'builtin'::character varying")),
        sa.Column('provider_id', sa.String(128), nullable=True),
        sa.Column('risk_level', sa.String(32), nullable=False, server_default=sa.text("'low'::character varying")),
        sa.Column('visibility', sa.String(32), nullable=False, server_default=sa.text("'private'::character varying")),
        sa.Column('allowed_pools', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('enabled', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('max_invocations_per_request', sa.Integer, nullable=False, server_default=sa.text('5')),
        sa.Column('cooldown_seconds', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('require_confirmation', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.PrimaryKeyConstraint('id', name='pk_tool_governance_policy_id'),
    )
    op.create_index('tool_governance_policy_tool_id_idx', 'tool_governance_policy', ['tool_id'])
    op.create_index('tool_governance_policy_source_type_idx', 'tool_governance_policy', ['source_type'])
    op.create_index('tool_governance_policy_risk_level_idx', 'tool_governance_policy', ['risk_level'])
    op.create_index('tool_governance_policy_visibility_idx', 'tool_governance_policy', ['visibility'])
    op.create_index('tool_governance_policy_enabled_idx', 'tool_governance_policy', ['enabled'])

    op.create_table(
        'tool_invocation_audit',
        sa.Column('id', sa.UUID, nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('tool_id', sa.String(128), nullable=False),
        sa.Column('tool_name', sa.String(256), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('account_id', sa.UUID, nullable=True),
        sa.Column('conversation_id', sa.UUID, nullable=True),
        sa.Column('invocation_status', sa.String(32), nullable=False, server_default=sa.text("'success'::character varying")),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP(0)')),
        sa.PrimaryKeyConstraint('id', name='pk_tool_invocation_audit_id'),
    )
    op.create_index('tool_invocation_audit_tool_id_idx', 'tool_invocation_audit', ['tool_id'])
    op.create_index('tool_invocation_audit_status_idx', 'tool_invocation_audit', ['invocation_status'])
    op.create_index('tool_invocation_audit_created_at_idx', 'tool_invocation_audit', ['created_at'])


def downgrade():
    op.drop_index('tool_invocation_audit_created_at_idx', table_name='tool_invocation_audit')
    op.drop_index('tool_invocation_audit_status_idx', table_name='tool_invocation_audit')
    op.drop_index('tool_invocation_audit_tool_id_idx', table_name='tool_invocation_audit')
    op.drop_table('tool_invocation_audit')

    op.drop_index('tool_governance_policy_enabled_idx', table_name='tool_governance_policy')
    op.drop_index('tool_governance_policy_visibility_idx', table_name='tool_governance_policy')
    op.drop_index('tool_governance_policy_risk_level_idx', table_name='tool_governance_policy')
    op.drop_index('tool_governance_policy_source_type_idx', table_name='tool_governance_policy')
    op.drop_index('tool_governance_policy_tool_id_idx', table_name='tool_governance_policy')
    op.drop_table('tool_governance_policy')
