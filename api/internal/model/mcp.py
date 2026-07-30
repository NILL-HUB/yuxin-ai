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

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    """返回无时区的 UTC 时间，兼容数据库 DateTime 列且避免 utcnow 退化警告。"""
    return datetime.now(UTC).replace(tzinfo=None)


class McpProvider(db.Model):
    """MCP 提供者模型"""
    __tablename__ = "mcp_provider"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_mcp_provider_id"),
        Index("mcp_provider_account_id_idx", "account_id"),
        Index("mcp_provider_is_public_idx", "is_public"),
        Index("mcp_provider_source_type_idx", "source_type"),
        Index("mcp_provider_category_idx", "category"),
        Index("mcp_provider_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    account_id = Column(UUID, ForeignKey("account.id"), nullable=True)
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    icon = Column(String(512), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    category = Column(String(255), nullable=False, server_default=text("''::character varying"))
    transport = Column(String(255), nullable=False, server_default=text("''::character varying"))
    url = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    command = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    headers = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    tool_names = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    args = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    env = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # 任务关键词列表，用于 ToolSelector 关键词快速匹配
    timeout_seconds = Column(Integer, nullable=False, server_default=text("30"))
    is_public = Column(Boolean, nullable=False, server_default=text("false"))
    source_type = Column(String(255), nullable=False, server_default=text("''::character varying"))
    source_key = Column(String(255), nullable=False, server_default=text("''::character varying"))
    source_url = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    published_at = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    account = relationship("Account", foreign_keys=[account_id], lazy="joined")
    tools = relationship("McpTool", back_populates="provider", cascade="all, delete-orphan", lazy="selectin")


class McpTool(db.Model):
    """MCP 工具元数据表（工具粒度，与 McpProvider 1:N 关联）。

    用途：供向量索引（mcp_index）和关键词检索使用。
    数据来源：MCP 注册/更新时调用 tools/list 拉取，或管理员手动触发同步。
    """
    __tablename__ = "mcp_tool"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_mcp_tool_id"),
        Index("mcp_tool_provider_id_idx", "provider_id"),
        Index("mcp_tool_name_idx", "name"),
        Index("mcp_tool_enabled_idx", "enabled"),
        Index("mcp_tool_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, nullable=False)
    provider_id = Column(UUID, ForeignKey("mcp_provider.id", ondelete="CASCADE"), nullable=False)
    # 工具名（MCP 协议 tools/list 返回的 name，如 get_issue）
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # 工具标题（MCP 协议的 title 字段，更人类可读）
    title = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # 工具描述（用于向量索引，核心字段）
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 输入参数 schema（MCP 协议的 inputSchema）
    input_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 输出 schema（MCP 协议的 outputSchema，部分 MCP server 提供）
    output_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # MCP 协议的 annotations（readOnlyHint 等提示）
    annotations = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 任务关键词（用于 ToolSelector 关键词快速匹配，同步时从 provider 继承或自动生成）
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # schema_hash：工具定义的哈希，用于检测变更、避免无意义的重写
    schema_hash = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # 同步状态：ready / stale / failed / empty
    sync_status = Column(String(64), nullable=False, server_default=text("'pending'::character varying"))
    last_synced_at = Column(DateTime, nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    provider = relationship("McpProvider", back_populates="tools", lazy="joined")

