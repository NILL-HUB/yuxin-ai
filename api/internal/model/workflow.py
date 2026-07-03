from sqlalchemy import (
    Column,
    UUID,
    String,
    Text,
    Boolean,
    DateTime,
    Float,
    Integer,
    text,
    PrimaryKeyConstraint,
    Index,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import UTC, datetime

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    """返回无时区的 UTC 时间，兼容数据库 DateTime 列且避免 utcnow 退化警告。"""
    return datetime.now(UTC).replace(tzinfo=None)
class Workflow(db.Model):
    """工作流模型"""
    __tablename__ = "workflow"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_id"),
        Index("workflow_account_id_idx", "account_id"),
        Index("workflow_tool_call_name_idx", "tool_call_name"),
        Index("workflow_is_public_idx", "is_public"),
        Index("workflow_tags_idx", "tags", postgresql_using="gin"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    account_id = Column(UUID, ForeignKey('account.id'), nullable=False)  # 创建账号id
    name = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 工作流名字
    tool_call_name = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 工作流工具调用名字
    icon = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 工作流图标
    description = Column(Text, nullable=False, server_default=text("''::text"))  # 应用描述
    graph = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 运行时配置
    draft_graph = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 草稿图配置
    is_debug_passed = Column(Boolean, nullable=False, server_default=text("false"))  # 是否调试通过
    status = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 工作流状态
    is_public = Column(Boolean, nullable=False, server_default=text("false"))  # 是否公开到广场
    tags = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))  # 工作流标签列表
    original_workflow_id = Column(UUID, nullable=True)  # 原始工作流ID（用于Fork追踪）
    published_at = Column(DateTime, nullable=True)  # 发布时间
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    # 关系定义
    account = relationship("Account", foreign_keys=[account_id], lazy="joined")
    versions = relationship(
        "WorkflowVersion",
        foreign_keys="WorkflowVersion.workflow_id",
        back_populates="workflow",
        lazy="selectin",
        order_by="WorkflowVersion.version.desc()",
    )


class WorkflowResult(db.Model):
    """工作流存储结果模型"""
    __tablename__ = "workflow_result"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_result_id"),
        Index("workflow_result_app_id_idx", "app_id"),
        Index("workflow_result_account_id_idx", "account_id"),
        Index("workflow_result_workflow_id_idx", "workflow_id"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))  # 结果id
    app_id = Column(UUID, nullable=True)  # 工作流调用的应用id，如果为空则代表非应用调用
    account_id = Column(UUID, nullable=False)  # 创建账号id
    workflow_id = Column(UUID, nullable=False)  # 结果关联的工作流id
    graph = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 运行时配置
    state = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 工作流最终状态
    latency = Column(Float, nullable=False, server_default=text("0.0"))  # 消息的总耗时
    status = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 运行状态
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class WorkflowVersion(db.Model):
    """工作流版本历史表，存储每次发布的 graph 快照，支持回滚到任意历史版本。

    对标 AppConfigVersion 的设计：
    - 每次 publish 时创建新版本记录
    - is_current_published 标记当前发布版本
    - 支持回滚：将历史版本 graph 复制回 draft_graph
    """
    __tablename__ = "workflow_version"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_version_id"),
        Index("workflow_version_workflow_id_idx", "workflow_id"),
        Index("workflow_version_is_current_idx", "is_current_published"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    workflow_id = Column(UUID, ForeignKey("workflow.id"), nullable=False)
    version = Column(Integer, nullable=False, server_default=text("1"))  # 版本号，递增
    graph = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 该版本的 graph 快照
    is_current_published = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )  # 是否是当前发布版本
    summary = Column(Text, nullable=False, server_default=text("''::text"))  # 版本说明/发布备注
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))

    # 关系定义
    workflow = relationship("Workflow", foreign_keys=[workflow_id], lazy="joined")
