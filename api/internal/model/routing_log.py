from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RoutingLog(Base):
    __tablename__ = "routing_log"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_routing_log_id"),
        Index("routing_log_account_id_idx", "account_id"),
        Index("routing_log_message_id_idx", "message_id"),
        Index("routing_log_status_idx", "status"),
        Index("routing_log_retention_expires_at_idx", "retention_expires_at"),
        Index("routing_log_latency_ms_idx", "latency_ms"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    message_id = Column(UUID, nullable=True)
    routing_decision = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    agent_candidates = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    filtered_out_agents = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    tool_candidates = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    filtered_out_tools = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    knowledge_hits = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    billing_events = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    invoke_from = Column(
        String(32), nullable=False, server_default=text("''::character varying")
    )
    user_query = Column(Text, nullable=True)
    task_classification = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    model_selection = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    agent_pool_hits = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    tool_pool_hits = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    key_usage = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    cost_summary = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    latency_ms = Column(Integer, nullable=False, server_default=text("0"))
    fallback_reason = Column(String(255), nullable=True)
    redaction_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    retention_expires_at = Column(DateTime, nullable=True)
    status = Column(
        String(64), nullable=False, server_default=text("'success'::character varying")
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    account = relationship("Account", foreign_keys=[account_id], lazy="joined")
