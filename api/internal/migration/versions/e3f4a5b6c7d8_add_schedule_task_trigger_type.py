"""add trigger_type / interval_config to schedule_task

Revision ID: e3f4a5b6c7d8
Revises: b6c7d8e9f0a1
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "e3f4a5b6c7d8"
down_revision = "b6c7d8e9f0a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("schedule_task", sa.Column("trigger_type", sa.String(length=16), nullable=False, server_default="cron"))
    op.add_column("schedule_task", sa.Column("interval_config", sa.dialects.postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))


def downgrade():
    op.drop_column("schedule_task", "interval_config")
    op.drop_column("schedule_task", "trigger_type")
