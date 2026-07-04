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


class WorkflowRun(db.Model):
    """工作流执行记录，每次工作流运行创建一条记录。

    对标 Dify 的 WorkflowRun，记录：
    - 触发信息（触发源、触发者）
    - 输入参数
    - 最终输出
    - 执行状态（running/succeeded/failed/stopped）
    - 总耗时
    - 关联的节点执行记录（通过 workflow_node_execution 表）
    """
    __tablename__ = "workflow_run"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_run_id"),
        Index("workflow_run_workflow_id_idx", "workflow_id"),
        Index("workflow_run_app_id_idx", "app_id"),
        Index("workflow_run_account_id_idx", "account_id"),
        Index("workflow_run_status_idx", "status"),
        Index("workflow_run_created_at_idx", "created_at"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    workflow_id = Column(UUID, ForeignKey("workflow.id"), nullable=False)  # 关联工作流
    app_id = Column(UUID, nullable=True)  # 调用工作流的应用ID（可选，直接调用为空）
    account_id = Column(UUID, nullable=False)  # 触发账号ID
    trigger_source = Column(String(32), nullable=False, server_default=text("'debug'::character varying"))  # 触发源: debug/app/schedule/api
    inputs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 输入参数
    outputs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 最终输出
    status = Column(String(32), nullable=False, server_default=text("'running'::character varying"))  # running/succeeded/failed/stopped
    error = Column(Text, nullable=False, server_default=text("''::text"))  # 错误信息
    total_steps = Column(Integer, nullable=False, server_default=text("0"))  # 总节点数
    elapsed_time = Column(Float, nullable=False, server_default=text("0.0"))  # 总耗时（秒）
    total_tokens = Column(Integer, nullable=False, server_default=text("0"))  # 总 token 消耗
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))


class WorkflowNodeExecution(db.Model):
    """工作流节点执行记录，每个节点的执行都会创建一条记录。

    对标 Dify 的 WorkflowNodeExecution，记录：
    - 节点基本信息（node_id, node_type, title）
    - 节点输入数据
    - 节点输出数据
    - 执行状态
    - 耗时
    - 错误信息
    - 重试信息
    """
    __tablename__ = "workflow_node_execution"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_workflow_node_execution_id"),
        Index("workflow_node_execution_run_id_idx", "workflow_run_id"),
        Index("workflow_node_execution_node_id_idx", "workflow_run_id", "node_id"),
        Index("workflow_node_execution_status_idx", "status"),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    workflow_run_id = Column(UUID, ForeignKey("workflow_run.id", ondelete="CASCADE"), nullable=False)  # 关联执行记录
    node_id = Column(UUID, nullable=False)  # 节点ID
    node_type = Column(String(32), nullable=False, server_default=text("''::character varying"))  # 节点类型
    title = Column(String(255), nullable=False, server_default=text("''::character varying"))  # 节点标题
    inputs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 节点输入
    outputs = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 节点输出
    status = Column(String(32), nullable=False, server_default=text("'running'::character varying"))  # running/succeeded/failed/skipped
    error = Column(Text, nullable=False, server_default=text("''::text"))  # 错误信息
    elapsed_time = Column(Float, nullable=False, server_default=text("0.0"))  # 耗时（秒）
    execution_metadata = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))  # 执行元数据（重试次数、token 消耗等）
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
