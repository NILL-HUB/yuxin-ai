from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AgentPoolConfig(db.Model):
    __tablename__ = "agent_pool_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_agent_pool_config_id"),
        Index("agent_pool_config_app_id_idx", "app_id"),
        Index("agent_pool_config_primary_pool_idx", "primary_pool"),
        Index("agent_pool_config_enabled_idx", "enabled"),
        Index("agent_pool_config_health_status_idx", "health_status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    app_id = Column(UUID, nullable=False)
    primary_pool = Column(String(64), nullable=False, server_default=text("'tenant'::character varying"))
    secondary_pools = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    risk_level = Column(String(32), nullable=False, server_default=text("'medium'::character varying"))
    model_tier = Column(String(32), nullable=False, server_default=text("'standard'::character varying"))
    model_id = Column(String(128), nullable=True)
    routing_priority = Column(Integer, nullable=False, server_default=text("100"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    health_status = Column(String(32), nullable=False, server_default=text("'unknown'::character varying"))
    last_health_check_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
