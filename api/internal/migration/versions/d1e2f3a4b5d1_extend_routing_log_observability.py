"""extend routing log observability

Revision ID: d1e2f3a4b5d1
Revises: d1e2f3a4b5d0
Create Date: 2026-06-16 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5d1'
down_revision = 'd1e2f3a4b5d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('routing_log', sa.Column('user_query', sa.Text(), nullable=True))
    op.add_column(
        'routing_log',
        sa.Column(
            'task_classification',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'model_selection',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'agent_pool_hits',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'tool_pool_hits',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'key_usage',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'cost_summary',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'latency_ms',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column('fallback_reason', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'routing_log',
        sa.Column(
            'redaction_enabled',
            sa.Boolean(),
            server_default=sa.text('false'),
            nullable=False,
        ),
    )
    op.add_column(
        'routing_log',
        sa.Column('retention_expires_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'routing_log_retention_expires_at_idx',
        'routing_log',
        ['retention_expires_at'],
    )
    op.create_index('routing_log_latency_ms_idx', 'routing_log', ['latency_ms'])


def downgrade():
    op.drop_index('routing_log_latency_ms_idx', table_name='routing_log')
    op.drop_index('routing_log_retention_expires_at_idx', table_name='routing_log')
    op.drop_column('routing_log', 'retention_expires_at')
    op.drop_column('routing_log', 'redaction_enabled')
    op.drop_column('routing_log', 'fallback_reason')
    op.drop_column('routing_log', 'latency_ms')
    op.drop_column('routing_log', 'cost_summary')
    op.drop_column('routing_log', 'key_usage')
    op.drop_column('routing_log', 'tool_pool_hits')
    op.drop_column('routing_log', 'agent_pool_hits')
    op.drop_column('routing_log', 'model_selection')
    op.drop_column('routing_log', 'task_classification')
    op.drop_column('routing_log', 'user_query')
