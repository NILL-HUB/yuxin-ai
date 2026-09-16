"""管理端 Agent 的会话与消息（设计 §10.1）。

**独立表**：不与用户端 `conversation` / `message` 混表。理由（设计 §11）：
用户端表没有 admin 标识列，admin 侧只能靠 `invoke_from` 约定区分；
独立表让"管理端对话"拥有自己的主键域与归属列（`admin_user_id`），
审计与归属判断不再需要猜测。
"""
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AdminAgentConversation(Base):
    __tablename__ = "admin_agent_conversation"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_conversation_id"),
        ForeignKeyConstraint(
            ["admin_agent_id"],
            ["admin_agent.id"],
            name="fk_admin_agent_conversation_agent_id_admin_agent",
            ondelete="CASCADE",
        ),
        Index("admin_agent_conversation_agent_idx", "admin_agent_id"),
        Index("admin_agent_conversation_admin_idx", "admin_user_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    admin_agent_id = Column(UUID, nullable=False)
    admin_user_id = Column(UUID, nullable=False)
    title = Column(String(255), nullable=False, server_default=text("''::character varying"))
    is_deleted = Column(Boolean, nullable=False, server_default=text("false"))
    updated_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )


class AdminAgentMessage(Base):
    __tablename__ = "admin_agent_message"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_admin_agent_message_id"),
        ForeignKeyConstraint(
            ["conversation_id"],
            ["admin_agent_conversation.id"],
            name="fk_admin_agent_message_conversation_id_admin_agent_conversation",
            ondelete="CASCADE",
        ),
        Index("admin_agent_message_conversation_idx", "conversation_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    conversation_id = Column(UUID, nullable=False)
    # user / assistant / tool（设计 §10.1 只规定 role + content + tool_calls）
    role = Column(String(32), nullable=False, server_default=text("'user'::character varying"))
    content = Column(Text, nullable=False, server_default=text("''::text"))
    # assistant：本次 LLM 产出的 tool_calls；tool：回灌结果（含 name/tool_call_id/result）
    tool_calls = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    updated_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
