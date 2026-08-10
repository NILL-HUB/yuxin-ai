from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    UUID,
    text,
)

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OrchestrationFeatureFlagModel(Base):
    __tablename__ = "orchestration_feature_flag"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_orchestration_feature_flag_id"),
        UniqueConstraint("code", name="uq_orchestration_feature_flag_code"),
        Index("orchestration_feature_flag_code_idx", "code"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    code = Column(String(128), nullable=False)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=False, server_default=text("''"))
    enabled = Column(Boolean, nullable=False, server_default=text("false"))
    risk_level = Column(String(64), nullable=False)
    fallback_behavior = Column(String(128), nullable=False)
    updated_by = Column(UUID, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
    )
