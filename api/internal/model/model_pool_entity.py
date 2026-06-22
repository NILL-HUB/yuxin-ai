from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ModelPoolConfig(db.Model):
    __tablename__ = "model_pool_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_pool_config_id"),
        Index("model_pool_config_provider_idx", "provider"),
        Index("model_pool_config_status_idx", "status"),
        Index("model_pool_config_tier_idx", "tier"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    provider = Column(String(128), nullable=False)
    model_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    tier = Column(String(64), nullable=False, server_default=text("'standard'::character varying"))
    capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    max_tokens = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))


class ModelKeyConfig(db.Model):
    __tablename__ = "model_key_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_key_config_id"),
        Index("model_key_config_provider_idx", "provider"),
        Index("model_key_config_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    provider = Column(String(128), nullable=False)
    key_alias = Column(String(255), nullable=False)
    key_value_encrypted = Column(Text, nullable=False, server_default=text("''::text"))
    tenant_quota = Column(Numeric(12, 4), nullable=False, server_default=text("0.0000"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    failure_count = Column(Integer, nullable=False, server_default=text("0"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))


class ModelTierPolicy(db.Model):
    __tablename__ = "model_tier_policy"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_tier_policy_id"),
        Index("model_tier_policy_code_idx", "tier_code", unique=True),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    tier_code = Column(String(64), nullable=False)
    allowed_models = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    default_model = Column(String(255), nullable=False, server_default=text("''::character varying"))
    routing_rules = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))


class CostPolicy(db.Model):
    __tablename__ = "cost_policy"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_cost_policy_id"),
        Index("cost_policy_name_idx", "policy_name", unique=True),
        Index("cost_policy_tier_idx", "model_tier"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    policy_name = Column(String(255), nullable=False)
    model_tier = Column(String(64), nullable=False, server_default=text("'standard'::character varying"))
    max_cost_per_request = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    billing_mode = Column(String(64), nullable=False, server_default=text("'token'::character varying"))
    upgrade_threshold = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
