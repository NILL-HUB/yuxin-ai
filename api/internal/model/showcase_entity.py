from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ShowcaseCase(db.Model):
    __tablename__ = "showcase_case"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_showcase_case_id"),
        Index("showcase_case_conversation_id_idx", "conversation_id"),
        Index("showcase_case_account_id_idx", "account_id"),
        Index("showcase_case_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    conversation_id = Column(UUID, nullable=False)
    account_id = Column(UUID, nullable=False)
    title = Column(String(200), nullable=False, server_default=text("''::character varying"))
    summary = Column(Text, nullable=False, server_default=text("''::text"))
    query = Column(Text, nullable=False, server_default=text("''::text"))
    answer = Column(Text, nullable=False, server_default=text("''::text"))
    tags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    rating = Column(Integer, nullable=False, server_default=text("5"))
    status = Column(String(32), nullable=False, server_default=text("'pending'::character varying"))
    reject_reason = Column(Text, nullable=False, server_default=text("''::text"))
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(UUID, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
