from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Text, UUID, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from internal.extension.database_extension import db
from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ScheduleTask(Base):
    __tablename__ = "schedule_task"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_schedule_task_id"),
        Index("ix_schedule_task_account", "account_id"),
        Index("ix_schedule_task_enabled", "enabled"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    owner_type = Column(String(16), nullable=False, server_default=text("'user'::character varying"))
    name = Column(String(128), nullable=False)
    prompt = Column(Text, nullable=False)
    trigger_type = Column(String(16), nullable=False, server_default=text("'cron'::character varying"))
    cron_expression = Column(String(64), nullable=False)
    cron_humanized = Column(String(255), nullable=False, server_default=text("''::character varying"))
    interval_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled = Column(db.Boolean, nullable=False, server_default=text("true"))
    status = Column(String(32), nullable=False, server_default=text("'active'::character varying"))
    description = Column(String(512), nullable=False, server_default=text("''::character varying"))
    context = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    run_count = Column(Integer, nullable=False, server_default=text("0"))
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(32), nullable=True)
    last_result = Column(Text, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)

    owner_account = relationship("Account", foreign_keys=[account_id], lazy="joined")


class ScheduleTaskRun(Base):
    __tablename__ = "schedule_task_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_schedule_task_run_id"),
        Index("ix_schedule_task_run_task", "schedule_task_id"),
        Index("ix_schedule_task_run_account", "account_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    schedule_task_id = Column(UUID, ForeignKey("schedule_task.id"), nullable=False)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    owner_type = Column(String(16), nullable=False, server_default=text("'user'::character varying"))
    trigger_source = Column(String(32), nullable=False, server_default=text("'schedule'::character varying"))
    status = Column(String(32), nullable=False, server_default=text("'running'::character varying"))
    started_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
    finished_at = Column(DateTime, nullable=True)
    result_summary = Column(Text, nullable=True)
    result_data = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    error_message = Column(Text, nullable=True)
    message_id = Column(UUID, nullable=True)

    schedule_task = relationship("ScheduleTask", foreign_keys=[schedule_task_id], lazy="joined")
