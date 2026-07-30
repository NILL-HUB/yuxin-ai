"""Builtin 工具元数据镜像表（YAML→DB 同步）。

设计要点：
- 启动时从 YAML 同步到 DB（BuiltinToolSyncService）
- 运行时 BuiltinProviderManager 优先从 DB 读取
- DB 不可用时回退到 YAML
- admin 后台可编辑 label/description/task_keywords/icon
- Python 执行代码仍在本地文件，不存 DB
"""
from sqlalchemy import (
    Column,
    UUID,
    String,
    Text,
    Boolean,
    DateTime,
    PrimaryKeyConstraint,
    Index,
    text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import UTC, datetime

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BuiltinToolProvider(db.Model):
    """Builtin 工具提供商元数据镜像表"""
    __tablename__ = "builtin_tool_provider"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_builtin_tool_provider_id"),
        Index("builtin_tool_provider_name_idx", "name"),
    )

    id = Column(UUID, nullable=False, server_default=text('uuid_generate_v4()'))
    name = Column(String(255), nullable=False, unique=True)  # 提供商唯一标识（如 time/google）
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    icon = Column(String(512), nullable=False, server_default=text("''::character varying"))
    background = Column(String(64), nullable=False, server_default=text("''::character varying"))
    category = Column(String(255), nullable=False, server_default=text("''::character varying"))
    # 元数据来源：catalog（YAML 同步）| custom（admin 自定义）
    source = Column(String(32), nullable=False, server_default=text("'catalog'::character varying"))
    # YAML 文件路径（用于回退和同步校验）
    source_path = Column(String(1024), nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text('CURRENT_TIMESTAMP(0)'),
        server_onupdate=text('CURRENT_TIMESTAMP(0)'),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP(0)'))

    # 关系
    tools = relationship("BuiltinTool", back_populates="provider", cascade="all, delete-orphan")

    @property
    def tool_entities(self):
        return self.tools


class BuiltinTool(db.Model):
    """Builtin 工具元数据镜像表（每个工具一行）"""
    __tablename__ = "builtin_tool"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_builtin_tool_id"),
        Index("builtin_tool_provider_id_idx", "provider_id"),
        Index("builtin_tool_name_idx", "name"),
        Index("builtin_tool_task_keywords_idx", "task_keywords", postgresql_using="gin"),
    )

    id = Column(UUID, nullable=False, server_default=text('uuid_generate_v4()'))
    provider_id = Column(UUID, ForeignKey('builtin_tool_provider.id'), nullable=False)
    name = Column(String(255), nullable=False)  # 工具名（如 current_time）
    label = Column(String(255), nullable=False, server_default=text("''::character varying"))
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # 工具参数定义（YAML 中的 params 字段，多数为空）
    params = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # 输出 schema（用于 Agent 选择工具时判断输出形态，可选字段）
    output_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 任务关键词（用于 ToolSelector 关键词快速匹配）
    task_keywords = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Python 模块路径（用于 dynamic_import 加载执行代码）
    python_module = Column(String(1024), nullable=False, server_default=text("''::character varying"))
    # 元数据来源：catalog（YAML 同步）| custom（admin 自定义）
    source = Column(String(32), nullable=False, server_default=text("'catalog'::character varying"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text('CURRENT_TIMESTAMP(0)'),
        server_onupdate=text('CURRENT_TIMESTAMP(0)'),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text('CURRENT_TIMESTAMP(0)'))

    # 关系
    provider = relationship("BuiltinToolProvider", back_populates="tools")
