"""Prompt 模板表。

存储系统级 prompt 模板，支持 YAML→DB 单向同步和 admin 自定义。
设计参照 builtin_tool 的 source=catalog/custom 双源保护机制。

用途：
- 指挥官 system prompt 从硬编码迁移到 DB 管理，方便迭代优化
- 未来 task_classifier、task_decomposer 等 prompt 也可纳入管理
- admin 后台可编辑 source="custom" 的 prompt，不被 YAML 同步覆盖
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PromptTemplate(db.Model):
    """Prompt 模板表。

    prompt_key 为主键，与 public_ai_feature_config.feature_key 对应但不强制外键关联。
    source=catalog 表示 YAML 同步来源，source=custom 表示 admin 自定义（不被覆盖）。
    """
    __tablename__ = "prompt_template"
    __table_args__ = (
        PrimaryKeyConstraint("prompt_key", name="pk_prompt_template_key"),
        Index("prompt_template_category_idx", "category"),
        Index("prompt_template_enabled_idx", "enabled"),
        Index("prompt_template_source_idx", "source"),
    )

    # prompt_key：业务键，如 conductor、task_classifier、task_decomposer
    prompt_key = Column(String(64), nullable=False)
    # 中文名称
    name = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # 分类：routing/conversation/memory/assistant/icon/general
    category = Column(String(64), nullable=False, server_default=text("'general'::character varying"))
    # 描述说明
    description = Column(Text, nullable=False, server_default=text("''::text"))
    # prompt 正文（支持 {max_agents} 等占位符，运行时 format）
    content = Column(Text, nullable=False, server_default=text("''::text"))
    # 占位符说明（供 admin 参考，如 {"max_agents": "最大 Agent 数量"}）
    variables = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # 来源：catalog=YAML 同步 / custom=admin 自定义
    source = Column(String(32), nullable=False, server_default=text("'catalog'::character varying"))
    # YAML 文件路径（source=catalog 时记录，用于回溯）
    source_path = Column(String(512), nullable=True)
    # 内容 hash（source=catalog 时用于增量更新检测）
    content_hash = Column(String(128), nullable=False, server_default=text("''::character varying"))
    # 是否启用
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # 版本号（每次更新自增，用于追踪迭代）
    version = Column(Integer, nullable=False, server_default=text("1"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
        onupdate=_utcnow_naive,
    )
    created_at = Column(
        DateTime,
        nullable=False,
        default=_utcnow_naive,
        server_default=text("CURRENT_TIMESTAMP(0)"),
    )
