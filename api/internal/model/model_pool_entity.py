from datetime import UTC, datetime
from uuid import uuid4

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
        Index("ix_model_pool_config_provider_model", "provider", "model_name"),
        Index("ix_model_pool_config_model_type", "model_type"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    provider = Column(String(128), nullable=False)
    model_name = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(String(512), nullable=False, server_default=text("''::character varying"))
    tier = Column(String(64), nullable=False, server_default=text("'2'::character varying"))
    capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    price_per_1k_tokens = Column(Numeric(12, 6), nullable=False, server_default=text("0.000000"))
    max_tokens = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    model_type = Column(String(32), nullable=False, server_default=text("'chat'::character varying"))
    compatible_api = Column(String(32), nullable=False, server_default=text("'openai'::character varying"))
    fallback_model_id = Column(String(36), nullable=True)
    priority = Column(Integer, nullable=False, server_default=text("0"))
    # embedding 模型专属：向量维度（仅 model_type='embedding' 时有意义）
    # 0 或 NULL 表示未配置，由 EmbeddingsService 内置字典兜底识别
    embedding_dimension = Column(Integer, nullable=True, server_default=text("0"))
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
        Index("model_key_config_model_id_idx", "model_id"),
        Index("model_key_config_expires_at_idx", "expires_at"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    provider = Column(String(128), nullable=False)
    key_alias = Column(String(255), nullable=False)
    key_value_encrypted = Column(Text, nullable=False, server_default=text("''::text"))
    tenant_quota = Column(Numeric(12, 4), nullable=False, server_default=text("0.0000"))
    status = Column(String(64), nullable=False, server_default=text("'active'::character varying"))
    failure_count = Column(Integer, nullable=False, server_default=text("0"))
    last_used_at = Column(DateTime, nullable=True)
    effective_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    used_credits = Column(Numeric(12, 4), nullable=False, server_default=text("0.0000"))
    model_id = Column(String(36), nullable=True)
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
    # tier_code: 数字字符串标识（"1","2","3"...），用户可自定义
    tier_code = Column(String(64), nullable=False)
    # tier_name: 显示名（如"经济型"、"标准型"），用户可自定义
    tier_name = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # sort_order: 排序序号，数字越小越靠前
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
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
    model_tier = Column(String(64), nullable=False, server_default=text("'2'::character varying"))
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
