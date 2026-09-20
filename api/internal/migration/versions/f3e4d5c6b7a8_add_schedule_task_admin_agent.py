"""add schedule task admin agent binding

Revision ID: f3e4d5c6b7a8
Revises: z3c4d5e6f7a8
Create Date: 2026-09-20 00:00:00.000000

ADMIN-P4 T3：定时任务 admin_agent 通道。
`schedule_task` / `schedule_task_run` 各加 `admin_agent_id`（UUID NULL，FK → admin_agent.id），
管理端 Agent 可被绑定到定时任务上周期执行板块动作。

down_revision 指向当前单 head `z3c4d5e6f7a8`。
"""
from alembic import op
import sqlalchemy as sa


revision = "f3e4d5c6b7a8"
down_revision = "z3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "schedule_task",
        sa.Column("admin_agent_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_schedule_task_admin_agent_id_admin_agent",
        "schedule_task",
        "admin_agent",
        ["admin_agent_id"],
        ["id"],
    )
    op.create_index(
        "ix_schedule_task_admin_agent", "schedule_task", ["admin_agent_id"]
    )

    op.add_column(
        "schedule_task_run",
        sa.Column("admin_agent_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_schedule_task_run_admin_agent_id_admin_agent",
        "schedule_task_run",
        "admin_agent",
        ["admin_agent_id"],
        ["id"],
    )
    op.create_index(
        "ix_schedule_task_run_admin_agent", "schedule_task_run", ["admin_agent_id"]
    )


def downgrade():
    op.drop_index("ix_schedule_task_run_admin_agent", table_name="schedule_task_run")
    op.drop_constraint(
        "fk_schedule_task_run_admin_agent_id_admin_agent",
        "schedule_task_run",
        type_="foreignkey",
    )
    op.drop_column("schedule_task_run", "admin_agent_id")

    op.drop_index("ix_schedule_task_admin_agent", table_name="schedule_task")
    op.drop_constraint(
        "fk_schedule_task_admin_agent_id_admin_agent",
        "schedule_task",
        type_="foreignkey",
    )
    op.drop_column("schedule_task", "admin_agent_id")
