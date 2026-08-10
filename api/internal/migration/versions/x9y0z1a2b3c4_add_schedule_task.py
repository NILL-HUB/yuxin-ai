"""add schedule task tables

Revision ID: x9y0z1a2b3c4
Revises: a1b2c3d4e5f7
Create Date: 2026-08-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'x9y0z1a2b3c4'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'schedule_task',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('cron_expression', sa.String(length=64), nullable=False),
        sa.Column('cron_humanized', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'active'::character varying"), nullable=False),
        sa.Column('description', sa.String(length=512), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('run_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('last_run_at', sa.DateTime(), nullable=True),
        sa.Column('last_run_status', sa.String(length=32), nullable=True),
        sa.Column('last_result', sa.Text(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], name='fk_schedule_task_account_id_account'),
        sa.PrimaryKeyConstraint('id', name='pk_schedule_task_id'),
    )
    op.create_index('ix_schedule_task_account', 'schedule_task', ['account_id'])
    op.create_index('ix_schedule_task_enabled', 'schedule_task', ['enabled'])

    op.create_table(
        'schedule_task_run',
        sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('schedule_task_id', sa.UUID(), nullable=False),
        sa.Column('account_id', sa.UUID(), nullable=False),
        sa.Column('trigger_source', sa.String(length=32), server_default=sa.text("'schedule'::character varying"), nullable=False),
        sa.Column('status', sa.String(length=32), server_default=sa.text("'running'::character varying"), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('result_summary', sa.Text(), nullable=True),
        sa.Column('result_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('message_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], name='fk_schedule_task_run_account_id_account'),
        sa.ForeignKeyConstraint(['schedule_task_id'], ['schedule_task.id'], name='fk_schedule_task_run_schedule_task_id'),
        sa.PrimaryKeyConstraint('id', name='pk_schedule_task_run_id'),
    )
    op.create_index('ix_schedule_task_run_task', 'schedule_task_run', ['schedule_task_id'])
    op.create_index('ix_schedule_task_run_account', 'schedule_task_run', ['account_id'])


def downgrade():
    op.drop_index('ix_schedule_task_run_account', table_name='schedule_task_run')
    op.drop_index('ix_schedule_task_run_task', table_name='schedule_task_run')
    op.drop_table('schedule_task_run')
    op.drop_index('ix_schedule_task_enabled', table_name='schedule_task')
    op.drop_index('ix_schedule_task_account', table_name='schedule_task')
    op.drop_table('schedule_task')
