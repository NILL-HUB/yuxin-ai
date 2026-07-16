# api/internal/model/model_provider_entity.py
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Index,
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


class ModelProviderConfig(db.Model):
    """模型供应商配置表 — 存储供应商元数据与统一 base_url"""
    __tablename__ = "model_provider_config"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_model_provider_config_id"),
        Index("ix_model_provider_config_name", "name", unique=True),
        Index("ix_model_provider_config_status", "status"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    name = Column(String(128), nullable=False)
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=True)
    icon = Column(String(512), nullable=True)
    background = Column(String(32), nullable=False, server_default=text("'#FFFFFF'::character varying"))
    default_base_url = Column(String(512), nullable=False)
    supported_model_types = Column(JSONB, nullable=False, server_default=text("'[\"chat\"]'::jsonb"))
    status = Column(String(32), nullable=False, server_default=text("'active'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
