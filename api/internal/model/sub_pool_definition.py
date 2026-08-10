from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class SubPoolDefinition(Base):
    __tablename__ = "sub_pool_definition"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_sub_pool_definition_id"),
        UniqueConstraint("pool_type", "name", name="uq_sub_pool_type_name"),
        Index("sub_pool_definition_type_idx", "pool_type"),
        Index("sub_pool_definition_enabled_idx", "enabled"),
    )

    id = Column(UUID, nullable=False, default=uuid4, server_default=text("uuid_generate_v4()"))
    pool_type = Column(String(32), nullable=False, server_default=text("'agent'"))
    name = Column(String(64), nullable=False)
    label = Column(String(128), nullable=False, server_default=text("''"))
    description = Column(Text, nullable=False, server_default=text("''"))
    visible_to_user = Column(Boolean, nullable=False, server_default=text("true"))
    default_enabled = Column(Boolean, nullable=False, server_default=text("true"))
    default_capabilities = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    is_system = Column(Boolean, nullable=False, server_default=text("false"))
    sort_order = Column(Integer, nullable=False, server_default=text("0"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("now()"), onupdate=_utcnow_naive)
