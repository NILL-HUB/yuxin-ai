from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, String, Text, UUID, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ToolConfirmation(db.Model):
    __tablename__ = "tool_confirmation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_tool_confirmation_id"),
        Index("tool_confirmation_owner_status_idx", "owner_account_id", "status"),
        Index("tool_confirmation_tool_name_idx", "tool_name"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    owner_account_id = Column(UUID, ForeignKey("account.id"), nullable=False)
    tool_name = Column(String(255), nullable=False)
    risk_level = Column(
        String(64), nullable=False, server_default=text("'high'::character varying")
    )
    tool_input = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(
        String(64), nullable=False, server_default=text("'pending'::character varying")
    )
    spent_credits = Column(Integer, nullable=False, server_default=text("0"))
    reason = Column(Text, nullable=False, server_default=text("''::text"))
    updated_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"), server_onupdate=text("CURRENT_TIMESTAMP(0)"), default=_utcnow_naive)
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    owner_account = relationship("Account", foreign_keys=[owner_account_id], lazy="joined")
