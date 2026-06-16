"""add routing quality feedback

Revision ID: d1e2f3a4b5d3
Revises: d1e2f3a4b5d2
Create Date: 2026-06-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd1e2f3a4b5d3'
down_revision = 'd1e2f3a4b5d2'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'routing_quality_feedback',
        sa.Column(
            'id',
            sa.UUID(),
            server_default=sa.text('uuid_generate_v4()'),
            nullable=False,
        ),
        sa.Column('routing_log_id', sa.UUID(), nullable=False),
        sa.Column('source', sa.String(length=64), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column(
            'dimension_scores',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'comment',
            sa.Text(),
            server_default=sa.text("''::text"),
            nullable=False,
        ),
        sa.Column(
            'metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id', name='pk_routing_quality_feedback_id'),
    )
    op.create_index(
        'routing_quality_feedback_routing_log_id_idx',
        'routing_quality_feedback',
        ['routing_log_id'],
    )
    op.create_table(
        'routing_optimization_suggestion',
        sa.Column(
            'id',
            sa.UUID(),
            server_default=sa.text('uuid_generate_v4()'),
            nullable=False,
        ),
        sa.Column('target_type', sa.String(length=64), nullable=False),
        sa.Column('target_id', sa.String(length=128), nullable=False),
        sa.Column('suggestion_type', sa.String(length=128), nullable=False),
        sa.Column('severity', sa.String(length=64), nullable=False),
        sa.Column(
            'reason',
            sa.Text(),
            server_default=sa.text("''::text"),
            nullable=False,
        ),
        sa.Column(
            'evidence',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            'status',
            sa.String(length=64),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            'id',
            name='pk_routing_optimization_suggestion_id',
        ),
    )
    op.create_index(
        'routing_optimization_suggestion_status_idx',
        'routing_optimization_suggestion',
        ['status'],
    )


def downgrade():
    op.drop_index(
        'routing_optimization_suggestion_status_idx',
        table_name='routing_optimization_suggestion',
    )
    op.drop_table('routing_optimization_suggestion')
    op.drop_index(
        'routing_quality_feedback_routing_log_id_idx',
        table_name='routing_quality_feedback',
    )
    op.drop_table('routing_quality_feedback')
