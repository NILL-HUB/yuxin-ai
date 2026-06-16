from datetime import UTC, datetime

from sqlalchemy import (
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

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RoutingQualityFeedbackModel(db.Model):
    __tablename__ = "routing_quality_feedback"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_routing_quality_feedback_id"),
        Index("routing_quality_feedback_routing_log_id_idx", "routing_log_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    routing_log_id = Column(UUID, nullable=False)
    source = Column(String(64), nullable=False)
    rating = Column(Integer, nullable=False)
    dimension_scores = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    comment = Column(Text, nullable=False, server_default=text("''::text"))
    meta = Column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_by = Column(UUID, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class RoutingOptimizationSuggestionModel(db.Model):
    __tablename__ = "routing_optimization_suggestion"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_routing_optimization_suggestion_id"),
        Index("routing_optimization_suggestion_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=False)
    suggestion_type = Column(String(128), nullable=False)
    severity = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False, server_default=text("''::text"))
    evidence = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(64), nullable=False, server_default=text("'open'"))
    created_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
