# api/internal/model/public_ai_feature_config.py
"""公共资源 AI 功能配置模型。

管理平台侧发起的、用户不承担成本的 AI 调用（图标生成、记忆巩固、意图识别等）
所使用的模型配置。每个 feature_key 独立配置一个 model_pool_config 中的模型。
"""
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from internal.extension.database_extension import db


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class PublicAIFeatureConfig(db.Model):
    """公共 AI 功能配置表。

    每行对应一个公共 AI 功能的模型配置，通过 model_config_id 引用模型池中的模型。
    feature_key 为业务键，硬编码在调用方代码中（如 "icon_generation"、"memory_consolidation"）。
    """
    __tablename__ = "public_ai_feature_config"
    __table_args__ = (
        Index("ix_public_ai_feature_category", "feature_category"),
        Index("ix_public_ai_feature_enabled", "enabled"),
    )

    # 业务键，如 icon_generation / memory_consolidation / intent_recognition
    feature_key = Column(String(64), primary_key=True)
    feature_name = Column(String(128), nullable=False)
    feature_category = Column(String(64), nullable=False, server_default=text("'general'::character varying"))
    feature_description = Column(String(512), nullable=True)
    # FK → model_pool_config.id，为空时使用 fallback_tier 自动选择
    model_config_id = Column(UUID, ForeignKey("model_pool_config.id", ondelete="SET NULL"), nullable=True)
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    # 未配置 model_config_id 时的回退档位：cheap / standard / strong
    fallback_tier = Column(String(64), nullable=False, server_default=text("'1'::character varying"))
    # 功能所需的模型类型：chat / image / embedding / rerank / audio
    # 降级路径和后台模型选择均按此字段过滤，防止类型不匹配
    model_type = Column(String(32), nullable=False, server_default=text("'chat'::character varying"))
    # 是否扣用户额度：True=用户直接受益应扣额度，False=系统承担不扣额度
    billable = Column(Boolean, nullable=False, server_default=text("false"))
    # 是否已废弃：指挥官模式下被替代的旧路由 feature_key 标记为 True
    # admin 后台展示时标注"仅指挥官禁用时生效"，便于识别和未来清理
    deprecated = Column(Boolean, nullable=False, server_default=text("false"))
    extra_config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        server_onupdate=text("CURRENT_TIMESTAMP(0)"),
        default=_utcnow_naive,
    )
    created_at = Column(DateTime, nullable=False, default=_utcnow_naive, server_default=text("CURRENT_TIMESTAMP(0)"))
