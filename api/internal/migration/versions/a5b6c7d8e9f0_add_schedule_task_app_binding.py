"""add schedule task app binding

Revision ID: a5b6c7d8e9f0
Revises: a9f0b1c2d3e8
Create Date: 2026-08-24 00:00:00.000000

定时任务支持绑定应用执行：
- app_id：绑定的应用（可空，空=通用助手任务）
- task_type：app_execution（绑定应用执行）/ assistant_chat（通用助手对话）
- input_params：绑定应用时的输入参数（JSONB）
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a5b6c7d8e9f0"
down_revision = "a9f0b1c2d3e8"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return rows.scalar() is not None


def upgrade():
    if not _has_column("schedule_task", "app_id"):
        op.add_column(
            "schedule_task",
            sa.Column("app_id", sa.UUID(), nullable=True),
        )
    if not _has_column("schedule_task", "task_type"):
        op.add_column(
            "schedule_task",
            sa.Column(
                "task_type",
                sa.String(length=32),
                nullable=False,
                server_default="assistant_chat",
            ),
        )
    if not _has_column("schedule_task", "input_params"):
        op.add_column(
            "schedule_task",
            sa.Column(
                "input_params",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    op.create_index(
        "ix_schedule_task_app_id",
        "schedule_task",
        ["app_id"],
    )


def downgrade():
    op.drop_index("ix_schedule_task_app_id", table_name="schedule_task")
    if _has_column("schedule_task", "input_params"):
        op.drop_column("schedule_task", "input_params")
    if _has_column("schedule_task", "task_type"):
        op.drop_column("schedule_task", "task_type")
    if _has_column("schedule_task", "app_id"):
        op.drop_column("schedule_task", "app_id")
