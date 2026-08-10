"""add owner_type to schedule_task and schedule_task_run

Revision ID: d1e2f3a4b5e6
Revises: a7b8c9d0e1f2
Create Date: 2026-08-08 00:00:00.000000

为定时任务增加归属方类型：'user'（用户端创建，按 account_id 隔离）与
'admin'（平台级任务，由管理员创建，执行时以系统账号 platform 身份走编排链）。
存量数据回填为 'user'，用户端行为完全不变。
"""
from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5e6'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'schedule_task',
        sa.Column(
            'owner_type',
            sa.String(length=16),
            server_default=sa.text("'user'::character varying"),
            nullable=False,
        ),
    )
    op.add_column(
        'schedule_task_run',
        sa.Column(
            'owner_type',
            sa.String(length=16),
            server_default=sa.text("'user'::character varying"),
            nullable=False,
        ),
    )


def downgrade():
    op.drop_column('schedule_task_run', 'owner_type')
    op.drop_column('schedule_task', 'owner_type')
