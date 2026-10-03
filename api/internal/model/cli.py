from datetime import UTC, datetime
import uuid

from sqlalchemy import (
    Column,
    UUID,
    String,
    Text,
    DateTime,
    Boolean,
    Integer,
    text,
    PrimaryKeyConstraint,
    Index,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    """返回无时区的 UTC 时间，兼容数据库 DateTime 列且避免 utcnow 退化警告。"""
    return datetime.now(UTC).replace(tzinfo=None)


class CliProvider(Base):
    """CLI 提供者模型"""
    __tablename__ = "cli_provider"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_cli_provider_id"),
        Index("cli_provider_account_id_idx", "account_id"),
        Index("cli_provider_is_public_idx", "is_public"),
        Index("cli_provider_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    icon = Column(String(512), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    category = Column(String(255), nullable=False, server_default=text("''::character varying"))
    command = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    args = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    env = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # CLI 工具声明：{tool_name: {"description": str, "parameters": {JSON Schema}}}
    tool_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    timeout_seconds = Column(Integer, nullable=False, server_default=text("30"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    is_public = Column(Boolean, nullable=False, server_default=text("false"))
    source_type = Column(String(64), nullable=False, server_default=text("'cli'::character varying"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    account = relationship("Account", foreign_keys=[account_id], lazy="joined")
    tools = relationship("CliTool", back_populates="provider", cascade="all, delete-orphan", lazy="selectin")


class CliTool(Base):
    """CLI 工具元数据表（工具粒度，与 CliProvider 1:N 关联）。"""
    __tablename__ = "cli_tool"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_cli_tool_id"),
        Index("cli_tool_provider_id_idx", "provider_id"),
        Index("cli_tool_name_idx", "name"),
        Index("cli_tool_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    provider_id = Column(UUID, ForeignKey("cli_provider.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    input_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    provider = relationship("CliProvider", back_populates="tools", lazy="joined")
