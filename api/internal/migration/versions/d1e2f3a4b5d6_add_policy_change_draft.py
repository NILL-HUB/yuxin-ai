"""add policy_change_draft table and extend suggestion

Revision ID: d1e2f3a4b5d6
Revises: d1e2f3a4b5d5
Create Date: 2026-06-18 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd1e2f3a4b5d6'
down_revision = 'd1e2f3a4b5d5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'policy_change_draft',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text("uuid_generate_v4()")),
        sa.Column('suggestion_id', sa.UUID(), nullable=False),
        sa.Column('policy_type', sa.String(64), nullable=False),
        sa.Column('target_id', sa.String(128), nullable=False, server_default=sa.text("''::character varying")),
        sa.Column('before_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('after_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('diff', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('impact', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('status', sa.String(64), nullable=False, server_default=sa.text("'pending'::character varying")),
        sa.Column('applied_by', sa.UUID(), nullable=True),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.Column('rolled_back_at', sa.DateTime(), nullable=True),
        sa.Column('rollback_reason', sa.Text(), nullable=False, server_default=sa.text("''::text")),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(0)")),
        sa.PrimaryKeyConstraint('id', name='pk_policy_change_draft_id'),
    )
    op.create_index('policy_change_draft_suggestion_id_idx', 'policy_change_draft', ['suggestion_id'])
    op.create_index('policy_change_draft_status_idx', 'policy_change_draft', ['status'])

    op.add_column('routing_optimization_suggestion', sa.Column('dismiss_reason', sa.Text(), nullable=False, server_default=sa.text("''::text")))
    op.add_column('routing_optimization_suggestion', sa.Column('applied_by', sa.UUID(), nullable=True))
    op.add_column('routing_optimization_suggestion', sa.Column('applied_at', sa.DateTime(), nullable=True))
    op.add_column('routing_optimization_suggestion', sa.Column('policy_change_draft_id', sa.UUID(), nullable=True))


def downgrade():
    op.drop_column('routing_optimization_suggestion', 'policy_change_draft_id')
    op.drop_column('routing_optimization_suggestion', 'applied_at')
    op.drop_column('routing_optimization_suggestion', 'applied_by')
    op.drop_column('routing_optimization_suggestion', 'dismiss_reason')
    op.drop_index('policy_change_draft_status_idx', table_name='policy_change_draft')
    op.drop_index('policy_change_draft_suggestion_id_idx', table_name='policy_change_draft')
    op.drop_table('policy_change_draft')
