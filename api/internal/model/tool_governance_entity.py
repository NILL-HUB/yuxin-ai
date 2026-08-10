from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ToolGovernancePolicy(Base):
    __tablename__ = "tool_governance_policy"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tool_governance_policy_id"),
        Index("tool_governance_policy_tool_id_idx", "tool_id"),
        Index("tool_governance_policy_source_type_idx", "source_type"),
        Index("tool_governance_policy_risk_level_idx", "risk_level"),
        Index("tool_governance_policy_visibility_idx", "visibility"),
        Index("tool_governance_policy_enabled_idx", "enabled"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    tool_id = Column(String(128), nullable=False)
    tool_name = Column(String(256), nullable=False, server_default=text("''::character varying"))
    source_type = Column(String(64), nullable=False, server_default=text("'builtin'::character varying"))
    provider_id = Column(String(128), nullable=True)
    risk_level = Column(String(32), nullable=False, server_default=text("'low'::character varying"))
    visibility = Column(String(32), nullable=False, server_default=text("'private'::character varying"))
    allowed_pools = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    max_invocations_per_request = Column(Integer, nullable=False, server_default=text("5"))
    cooldown_seconds = Column(Integer, nullable=False, server_default=text("0"))
    require_confirmation = Column(Boolean, nullable=False, server_default=text("false"))
    description = Column(Text, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))


class ToolInvocationAudit(Base):
    __tablename__ = "tool_invocation_audit"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tool_invocation_audit_id"),
        Index("tool_invocation_audit_tool_id_idx", "tool_id"),
        Index("tool_invocation_audit_status_idx", "invocation_status"),
        Index("tool_invocation_audit_created_at_idx", "created_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    tool_id = Column(String(128), nullable=False)
    tool_name = Column(String(256), nullable=False, server_default=text("''::character varying"))
    account_id = Column(UUID, nullable=True)
    conversation_id = Column(UUID, nullable=True)
    invocation_status = Column(String(32), nullable=False, server_default=text("'success'::character varying"))
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
