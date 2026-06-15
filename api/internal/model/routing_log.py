from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RoutingLog(db.Model):
    __tablename__ = "routing_log"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_routing_log_id"),
        Index("routing_log_account_id_idx", "account_id"),
        Index("routing_log_message_id_idx", "message_id"),
        Index("routing_log_status_idx", "status"),
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
