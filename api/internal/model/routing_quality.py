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

from pkg.sqlalchemy import Base


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class RoutingQualityFeedbackModel(Base):
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


class RoutingOptimizationSuggestionModel(Base):
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
    dismiss_reason = Column(Text, nullable=False, server_default=text("''::text"))
    applied_by = Column(UUID, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    policy_change_draft_id = Column(UUID, nullable=True)
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


class PolicyChangeDraftModel(Base):
    """策略变更草稿（已泛化为**通用 admin 变更草稿**，设计 §5.2）。

    泛化说明：
    - ``suggestion_id`` 可空——通用草稿（如 builtin_tool 的启停建议）不来自
      路由调优建议。路由路径仍会写入它，既有取值保持兼容。
    - ``policy_type`` 语义扩展为**板块标识**（承载任意 admin 板块，如
      ``builtin_tool`` / ``prompt_template``）；路由三个既有取值
      （``model_routing`` / ``tool_policy`` / ``agent_policy``）保持不变。
    - 无任何外键（与原设计一致）：草稿是台账，主体被删也要留住痕迹。
    """

    __tablename__ = "policy_change_draft"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_policy_change_draft_id"),
        Index("policy_change_draft_suggestion_id_idx", "suggestion_id"),
        Index("policy_change_draft_status_idx", "status"),
        # 通用草稿需要「列出全部板块的待应用草稿」这条查询
        Index(
            "policy_change_draft_status_created_idx",
            "status",
            "created_at",
        ),
    )

    id = Column(UUID, nullable=False, server_default=text("uuid_generate_v4()"))
    # 来源调优建议；通用草稿为 NULL（路由路径仍写入，保持兼容）
    suggestion_id = Column(UUID, nullable=True)
    policy_type = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=False, server_default=text("''::character varying"))
    before_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    after_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    diff = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    impact = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(64), nullable=False, server_default=text("'pending'"))
    applied_by = Column(UUID, nullable=True)
    applied_at = Column(DateTime, nullable=True)
    rolled_back_at = Column(DateTime, nullable=True)
    rollback_reason = Column(Text, nullable=False, server_default=text("''::text"))
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
