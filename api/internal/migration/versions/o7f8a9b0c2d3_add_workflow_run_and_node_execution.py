"""add workflow_run and workflow_node_execution tables

Revision ID: o7f8a9b0c2d3
Revises: n6e7f8a9b0c1
Create Date: 2026-07-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'o7f8a9b0c2d3'
down_revision = 'n6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade():
    # 创建 workflow_run 表
    op.create_table(
        'workflow_run',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('workflow_id', sa.UUID(), nullable=False),
        sa.Column('app_id', sa.UUID(), nullable=True),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column(
            'trigger_source',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'debug'::character varying"),
        ),
        sa.Column(
            'inputs',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'outputs',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'status',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'running'::character varying"),
        ),
        sa.Column(
            'error',
            sa.Text(),
            nullable=False,
            server_default=sa.text("''::text"),
        ),
        sa.Column(
            'total_steps',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
        sa.Column(
            'elapsed_time',
            sa.Float(),
            nullable=False,
            server_default=sa.text('0.0'),
        ),
        sa.Column(
            'total_tokens',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            server_onupdate=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.ForeignKeyConstraint(
            ['workflow_id'], ['workflow.id'],
            name='fk_workflow_run_workflow_id_workflow',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_run_id'),
    )
    op.create_index('workflow_run_workflow_id_idx', 'workflow_run', ['workflow_id'])
    op.create_index('workflow_run_app_id_idx', 'workflow_run', ['app_id'])
    op.create_index('workflow_run_account_id_idx', 'workflow_run', ['account_id'])
    op.create_index('workflow_run_status_idx', 'workflow_run', ['status'])
    op.create_index('workflow_run_created_at_idx', 'workflow_run', ['created_at'])

    # 创建 workflow_node_execution 表
    op.create_table(
        'workflow_node_execution',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('uuid_generate_v4()')),
        sa.Column('workflow_run_id', sa.UUID(), nullable=False),
        sa.Column('node_id', sa.UUID(), nullable=False),
        sa.Column(
            'node_type',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            'title',
            sa.String(length=255),
            nullable=False,
            server_default=sa.text("''::character varying"),
        ),
        sa.Column(
            'inputs',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'outputs',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'status',
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'running'::character varying"),
        ),
        sa.Column(
            'error',
            sa.Text(),
            nullable=False,
            server_default=sa.text("''::text"),
        ),
        sa.Column(
            'elapsed_time',
            sa.Float(),
            nullable=False,
            server_default=sa.text('0.0'),
        ),
        sa.Column(
            'execution_metadata',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
            server_onupdate=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP(0)'),
        ),
        sa.ForeignKeyConstraint(
            ['workflow_run_id'], ['workflow_run.id'],
            name='fk_workflow_node_execution_workflow_run_id_workflow_run',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='pk_workflow_node_execution_id'),
    )
    op.create_index(
        'workflow_node_execution_run_id_idx',
        'workflow_node_execution',
        ['workflow_run_id'],
    )
    op.create_index(
        'workflow_node_execution_node_id_idx',
        'workflow_node_execution',
        ['workflow_run_id', 'node_id'],
    )
    op.create_index(
        'workflow_node_execution_status_idx',
        'workflow_node_execution',
        ['status'],
    )


def downgrade():
    op.drop_index('workflow_node_execution_status_idx', table_name='workflow_node_execution')
    op.drop_index('workflow_node_execution_node_id_idx', table_name='workflow_node_execution')
    op.drop_index('workflow_node_execution_run_id_idx', table_name='workflow_node_execution')
    op.drop_table('workflow_node_execution')

    op.drop_index('workflow_run_created_at_idx', table_name='workflow_run')
    op.drop_index('workflow_run_status_idx', table_name='workflow_run')
    op.drop_index('workflow_run_account_id_idx', table_name='workflow_run')
    op.drop_index('workflow_run_app_id_idx', table_name='workflow_run')
    op.drop_index('workflow_run_workflow_id_idx', table_name='workflow_run')
    op.drop_table('workflow_run')
